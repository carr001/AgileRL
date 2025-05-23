import os

import h5py
import numpy as np
from accelerate import Accelerator
from torch.utils.data import DataLoader
from tqdm import trange

from agilerl.components.data import ReplayDataset
from agilerl.components.replay_buffer import ReplayBuffer
from agilerl.components.sampler import Sampler
from agilerl.hpo.mutation import Mutations
from agilerl.hpo.tournament import TournamentSelection
from agilerl.utils.algo_utils import obs_channels_to_first
from agilerl.utils.utils import (
    create_population,
    make_vect_envs,
    observation_space_channels_to_first,
)

# !Note: If you are running this demo without having installed agilerl,
# uncomment and place the following above agilerl imports:

# import sys
# sys.path.append('../')


if __name__ == "__main__":
    accelerator = Accelerator()

    accelerator.wait_for_everyone()
    if accelerator.is_main_process:
        print("===== AgileRL Offline Distributed Demo =====")
    accelerator.wait_for_everyone()

    NET_CONFIG = {
        "encoder_config": {
            "hidden_size": [32, 32],  # Actor hidden size
        }
    }

    INIT_HP = {
        "DOUBLE": True,  # Use double Q-learning
        "BATCH_SIZE": 128,  # Batch size
        "LR": 1e-3,  # Learning rate
        "GAMMA": 0.99,  # Discount factor
        "LEARN_STEP": 1,  # Learning frequency
        "TAU": 1e-3,  # For soft update of target network parameters
        # Swap image channels dimension from last to first [H, W, C] -> [C, H, W]
        "CHANNELS_LAST": False,
        "POP_SIZE": 4,  # Population size
    }

    num_envs = 1
    env = make_vect_envs("CartPole-v1")  # Create environment
    dataset = h5py.File("data/cartpole/cartpole_random_v1.1.0.h5", "r")  # Load dataset

    observation_space = env.single_observation_space
    action_space = env.single_action_space
    if INIT_HP["CHANNELS_LAST"]:
        observation_space = observation_space_channels_to_first(observation_space)

    pop = create_population(
        algo="CQN",  # Algorithm
        observation_space=observation_space,  # Observation space
        action_space=action_space,  # Action space
        net_config=NET_CONFIG,  # Network configuration
        INIT_HP=INIT_HP,  # Initial hyperparameters
        population_size=INIT_HP["POP_SIZE"],  # Population size
        num_envs=num_envs,  # Number of vectorized envs
        accelerator=accelerator,  # Accelerator
    )

    field_names = ["state", "action", "reward", "next_state", "done"]
    memory = ReplayBuffer(
        memory_size=10000,  # Max replay buffer size
        field_names=field_names,
    )  # Field names to store in memory

    if accelerator.is_main_process:
        print("Filling replay buffer with dataset...")
    accelerator.wait_for_everyone()

    # Save transitions to replay buffer
    dataset_length = dataset["rewards"].shape[0]

    for i in trange(dataset_length - 1):
        state = dataset["observations"][i]
        next_state = dataset["observations"][i + 1]
        if INIT_HP["CHANNELS_LAST"]:
            state = obs_channels_to_first(state)
            next_state = obs_channels_to_first(next_state)
        action = dataset["actions"][i]
        reward = dataset["rewards"][i]
        done = bool(dataset["terminals"][i])
        # Save experience to replay buffer
        memory.save_to_memory(state, action, reward, next_state, done)

    # Create dataloader from replay buffer
    replay_dataset = ReplayDataset(memory, INIT_HP["BATCH_SIZE"])
    replay_dataloader = DataLoader(replay_dataset, batch_size=None)
    replay_dataloader = accelerator.prepare(replay_dataloader)
    sampler = Sampler(
        distributed=True, dataset=replay_dataset, dataloader=replay_dataloader
    )

    tournament = TournamentSelection(
        tournament_size=2,  # Tournament selection size
        elitism=True,  # Elitism in tournament selection
        population_size=INIT_HP["POP_SIZE"],  # Population size
        eval_loop=1,  # Evaluate using last N fitness scores
    )

    mutations = Mutations(
        algo="CQN",  # Algorithm
        no_mutation=0.4,  # No mutation
        architecture=0.2,  # Architecture mutation
        new_layer_prob=0.2,  # New layer mutation
        parameters=0.2,  # Network parameters mutation
        activation=0,  # Activation layer mutation
        rl_hp=0.2,  # Learning HP mutation
        rl_hp_selection=["lr", "batch_size"],  # Learning HPs to choose from
        mutation_sd=0.1,  # Mutation strength  # Network architecture
        rand_seed=1,  # Random seed
        accelerator=accelerator,  # Accelerator
    )

    max_steps = 50000  # Max steps

    evo_steps = 5000  # Evolution frequency
    eval_steps = None  # Evaluation steps per episode - go until done
    eval_loop = 1  # Number of evaluation episodes

    total_steps = 0

    accel_temp_models_path = "models/{}".format("CartPole-v1")
    if accelerator.is_main_process:
        if not os.path.exists(accel_temp_models_path):
            os.makedirs(accel_temp_models_path)

    print(f"\nDistributed training on {accelerator.device}...")

    # TRAINING LOOP
    print("Training...")
    pbar = trange(max_steps, unit="step")
    while np.less([agent.steps[-1] for agent in pop], max_steps).all():
        if accelerator is not None:
            accelerator.wait_for_everyone()
        for agent in pop:  # Loop through population
            for idx_step in range(evo_steps):
                # Sample dataloader
                experiences = sampler.sample(agent.batch_size)
                # Learn according to agent's RL algorithm
                agent.learn(experiences)
            total_steps += evo_steps
            agent.steps[-1] += evo_steps
            pbar.update(evo_steps)

        # Evaluate population
        fitnesses = [
            agent.test(
                env,
                swap_channels=INIT_HP["CHANNELS_LAST"],
                max_steps=eval_steps,
                loop=eval_loop,
            )
            for agent in pop
        ]

        if accelerator.is_main_process:
            print(f"--- Global Steps {total_steps} ---")
            print(f"Steps {[agent.steps[-1] for agent in pop]}")
            print(f'Fitnesses: {["%.2f"%fitness for fitness in fitnesses]}')
            print(
                f'5 fitness avgs: {["%.2f"%np.mean(agent.fitness[-5:]) for agent in pop]}'
            )

        # Tournament selection and population mutation
        accelerator.wait_for_everyone()
        for model in pop:
            model.unwrap_models()
        accelerator.wait_for_everyone()
        if accelerator.is_main_process:
            elite, pop = tournament.select(pop)
            pop = mutations.mutation(pop)
            for pop_i, model in enumerate(pop):
                model.save_checkpoint(f"{accel_temp_models_path}/CQN_{pop_i}.pt")
        accelerator.wait_for_everyone()
        if not accelerator.is_main_process:
            for pop_i, model in enumerate(pop):
                model.load_checkpoint(f"{accel_temp_models_path}/CQN_{pop_i}.pt")
        accelerator.wait_for_everyone()
        for model in pop:
            model.wrap_models()

    pbar.close()
    env.close()
