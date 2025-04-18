from unittest.mock import MagicMock, Mock, patch

import gymnasium as gym
import numpy as np
import pytest
import torch
from gymnasium import spaces
from pettingzoo.mpe import simple_speaker_listener_v4

from agilerl.algorithms import (
    CQN,
    DDPG,
    DQN,
    IPPO,
    MADDPG,
    MATD3,
    PPO,
    TD3,
    RainbowDQN,
)
from agilerl.algorithms.core import EvolvableAlgorithm
from agilerl.utils.utils import (
    aggregate_metrics_across_gpus,
    calculate_vectorized_scores,
    create_population,
    gather_tensor,
    make_multi_agent_vect_envs,
    make_skill_vect_envs,
    make_vect_envs,
    plot_population_score,
    print_hyperparams,
    save_llm_checkpoint,
)
from agilerl.wrappers.learning import Skill

# Shared HP dict that can be used by any algorithm
SHARED_INIT_HP = {
    "POPULATION_SIZE": 4,
    "DOUBLE": True,
    "BATCH_SIZE": 128,
    "CUDAGRAPHS": False,
    "LR": 1e-3,
    "LR_ACTOR": 1e-4,
    "LR_CRITIC": 1e-3,
    "GAMMA": 0.99,
    "LEARN_STEP": 1,
    "TAU": 1e-3,
    "BETA": 0.4,
    "PRIOR_EPS": 0.000001,
    "NUM_ATOMS": 51,
    "V_MIN": 0,
    "V_MAX": 200,
    "N_STEP": 3,
    "POLICY_FREQ": 10,
    "GAE_LAMBDA": 0.95,
    "ACTION_STD_INIT": 0.6,
    "CLIP_COEF": 0.2,
    "ENT_COEF": 0.01,
    "VF_COEF": 0.5,
    "MAX_GRAD_NORM": 0.5,
    "TARGET_KL": None,
    "UPDATE_EPOCHS": 4,
    "AGENT_IDS": ["agent1", "agent2"],
    "LAMBDA": 1.0,
    "REG": 0.000625,
    "CHANNELS_LAST": False,
    "O_U_NOISE": True,
    "EXPL_NOISE": 0.1,
    "MEAN_NOISE": 0.0,
    "THETA": 0.15,
    "DT": 0.01,
}


# Returns an AsyncVectorEnv object when given a valid environment name and number of environments
def test_returns_asyncvectorenv_object():
    num_envs = 3
    env = make_vect_envs("CartPole-v1", num_envs=num_envs)
    assert isinstance(env, gym.vector.AsyncVectorEnv)
    assert env.num_envs == num_envs


# Returns an AsyncVectorEnv object when given a valid environment name and number of environments
def test_returns_asyncvectorenv_object_multiagent():
    num_envs = 3
    env = simple_speaker_listener_v4.parallel_env
    env_kwargs = {"continuous_actions": False}
    env = make_multi_agent_vect_envs(env, num_envs=num_envs, **env_kwargs)
    env.close()
    assert env.num_envs == num_envs


# Returns an AsyncVectorEnv object when given a valid environment name and number of environments
def test_returns_asyncvectorenv_object_skill():
    num_envs = 3
    skill = Skill
    env = make_skill_vect_envs("CartPole-v1", skill=skill, num_envs=num_envs)
    assert isinstance(env, gym.vector.AsyncVectorEnv)
    assert env.num_envs == num_envs


# Can create a population of agent for each single agent algorithm
def test_create_initial_population_single_agent():
    observation_space = spaces.Box(0, 1, shape=(4,))
    continuous_action_space = spaces.Box(0, 1, shape=(2,))
    discrete_action_space = spaces.Discrete(2)
    net_config = {"encoder_config": {"hidden_size": [8, 8]}}
    population_size = 4
    device = "cpu"
    accelerator = None

    algo_classes = {
        "DQN": DQN,
        "Rainbow DQN": RainbowDQN,
        "DDPG": DDPG,
        "TD3": TD3,
        "PPO": PPO,
        "CQN": CQN,
    }

    for algo in algo_classes.keys():
        if algo in ["TD3", "DDPG"]:
            action_space = continuous_action_space
        else:
            action_space = discrete_action_space

        population = create_population(
            algo=algo,
            observation_space=observation_space,
            action_space=action_space,
            net_config=net_config,
            INIT_HP=SHARED_INIT_HP,
            population_size=population_size,
            device=device,
            accelerator=accelerator,
        )
        assert len(population) == population_size
        for agent in population:
            assert isinstance(agent, algo_classes[algo])
            assert agent.observation_space == observation_space
            assert agent.action_space == action_space
            assert agent.device == "cpu"
            assert agent.accelerator is None


# Can create a population of agent for each multi agent algorithm
def test_create_initial_population_multi_agent():
    observation_space = [spaces.Box(0, 1, shape=(4,)) for _ in range(2)]
    action_space = [spaces.Discrete(2) for _ in range(2)]
    net_config = {"encoder_config": {"hidden_size": [8]}}
    population_size = 4
    device = "cpu"
    accelerator = None

    algo_classes = {
        "MADDPG": MADDPG,
        "MATD3": MATD3,
        "IPPO": IPPO,
    }

    for algo in algo_classes.keys():
        population = create_population(
            algo=algo,
            observation_space=observation_space,
            action_space=action_space,
            net_config=net_config,
            INIT_HP=SHARED_INIT_HP,
            population_size=population_size,
            device=device,
            accelerator=accelerator,
        )
        assert len(population) == population_size
        for agent in population:
            assert isinstance(agent, algo_classes[algo])
            assert agent.observation_spaces == observation_space
            assert agent.action_spaces == action_space
            assert agent.device == "cpu"
            assert agent.accelerator is None


# The function returns a list of episode rewards from the first episode in each parallel environment.
def test_returns_list_of_episode_rewards():
    rewards = np.array([[1, 2, 3, 4, 5], [4, 5, 6, 7, 8]])
    terminations = np.array([[0, 0, 1, 0, 1], [0, 1, 0, 0, 0]])
    expected_rewards = [6, 9]

    result = calculate_vectorized_scores(
        rewards, terminations, include_unterminated=False, only_first_episode=True
    )

    assert result == expected_rewards


# The function returns a list of episode rewards including all episodes.
def test_returns_list_of_episode_rewards_including_unterminated():
    rewards = np.array([[1, 2, 3], [4, 5, 6]])
    terminations = np.array([[0, 0, 1], [0, 1, 0]])
    expected_rewards = [6, 9, 6]

    result = calculate_vectorized_scores(
        rewards, terminations, include_unterminated=True, only_first_episode=False
    )

    assert result == expected_rewards


# The function returns a list of episode rewards including all terminated episodes.
def test_returns_list_of_episode_rewards_all_terminated_episodes():
    rewards = np.array([[1, 2, 3, 4, 5], [4, 5, 6, 7, 8]])
    terminations = np.array([[0, 0, 1, 0, 1], [0, 1, 0, 0, 0]])
    expected_rewards = [6, 9, 9]

    result = calculate_vectorized_scores(
        rewards, terminations, include_unterminated=False, only_first_episode=False
    )

    assert result == expected_rewards


# The function returns a list of episode rewards including all terminated episodes.
def test_returns_list_of_episode_rewards_including_all_terminated_episodes():
    rewards = np.array([[1, 2, 3, 4, 5], [4, 5, 6, 7, 8]])
    terminations = np.array([[0, 0, 1, 0, 1], [0, 1, 0, 0, 0]])
    expected_rewards = [6, 9, 9]

    result = calculate_vectorized_scores(
        rewards, terminations, include_unterminated=False, only_first_episode=False
    )

    assert result == expected_rewards


# The function returns a list of episode rewards containing no terminated episodes.
def test_returns_list_of_episode_rewards_with_no_terminations():
    rewards = np.array([[1, 2, 3, 4, 5], [4, 5, 6, 7, 8]])
    terminations = np.array([[0, 0, 0, 0, 0], [0, 0, 0, 0, 0]])
    expected_rewards = [15, 30]

    result = calculate_vectorized_scores(
        rewards, terminations, include_unterminated=True, only_first_episode=False
    )

    assert result == expected_rewards


# The function prints the hyperparameters and fitnesses of all agents in the population.
def test_prints_hyperparams():
    # Arrange
    observation_space = spaces.Box(0, 1, shape=(4,))
    action_space = spaces.Discrete(2)
    net_config = {"encoder_config": {"hidden_size": [8]}}
    population_size = 1
    device = "cpu"
    accelerator = None
    algo = "DQN"

    pop = create_population(
        algo=algo,
        observation_space=observation_space,
        action_space=action_space,
        net_config=net_config,
        INIT_HP=SHARED_INIT_HP,
        population_size=population_size,
        device=device,
        accelerator=accelerator,
    )

    # Manually set attributes
    pop[0].fitness = [1, 2, 3]
    pop[0].lr = 0.01
    pop[0].batch_size = 32

    expected_output = "Agent ID: {}    Mean 5 Fitness: {:.2f}    Attributes: {}".format(
        pop[0].index,
        np.mean(pop[0].fitness[-5:]),
        EvolvableAlgorithm.inspect_attributes(pop[0]),
    )

    with patch("builtins.print") as mock_print:
        print_hyperparams(pop)
        mock_print.assert_called_once_with(expected_output)


# The function should correctly plot the fitness scores of all agents in the population.
@patch("agilerl.utils.utils.plt")
def test_plot_fitness_scores_all_agents(mock_plt):
    # Create a population of agents with fitness scores
    class Agent:
        def __init__(self, fitness):
            self.fitness = fitness
            self.steps = list(range(len(fitness) + 1))

    pop = [Agent([1, 2, 3]), Agent([4, 5, 6]), Agent([7, 8, 9])]

    # Call the function under test
    plot_population_score(pop)

    # Assert plotting functions have been called with expected args
    mock_plt.title.assert_called_once_with("Score History - Mutations")
    mock_plt.xlabel.assert_called_once_with("Steps")

    # Assert plt.figure got called
    assert mock_plt.figure.called


@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.local_rank = 0
    return agent


@patch("torch.distributed.get_world_size")
@patch("torch.distributed.all_gather")
def test_gather_tensor_with_tensor_input(
    mock_all_gather, mock_get_world_size, mock_agent
):
    mock_get_world_size.return_value = 3
    input_tensor = torch.tensor([1.0, 2.0, 3.0], device=f"cuda:{mock_agent.local_rank}")

    def mock_gather(output_list, input_tensor):
        output_list[0].copy_(
            torch.tensor([1.0, 2.0, 3.0], device=f"cuda:{mock_agent.local_rank}")
        )
        output_list[1].copy_(
            torch.tensor([4.0, 5.0, 6.0], device=f"cuda:{mock_agent.local_rank}")
        )
        output_list[2].copy_(
            torch.tensor([7.0, 8.0, 9.0], device=f"cuda:{mock_agent.local_rank}")
        )

    mock_all_gather.side_effect = mock_gather
    mock_agent.device = f"cuda:{mock_agent.local_rank}"
    result = gather_tensor(input_tensor, mock_agent)
    expected = torch.tensor(
        [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]],
        device=f"cuda:{mock_agent.local_rank}",
    )
    assert torch.allclose(result, expected)
    mock_get_world_size.assert_called_once()
    mock_all_gather.assert_called_once()


@patch("torch.distributed.get_world_size")
@patch("torch.distributed.all_gather")
def test_gather_tensor_with_scalar_input(
    mock_all_gather, mock_get_world_size, mock_agent
):
    mock_get_world_size.return_value = 2
    input_scalar = 42.0

    def mock_gather(output_list, input_tensor):
        output_list[0].copy_(torch.tensor(42.0, device=f"cuda:{mock_agent.local_rank}"))
        output_list[1].copy_(torch.tensor(84.0, device=f"cuda:{mock_agent.local_rank}"))

    mock_all_gather.side_effect = mock_gather
    mock_agent.device = f"cuda:{mock_agent.local_rank}"
    result = gather_tensor(input_scalar, mock_agent)
    expected = torch.tensor([42.0, 84.0], device=f"cuda:{mock_agent.local_rank}")
    assert torch.allclose(result, expected)
    mock_get_world_size.assert_called_once()
    mock_all_gather.assert_called_once()


@pytest.fixture
def setup_test_data():
    agent = Mock()
    agent.device = torch.device("cpu")
    agent.world_size = 4
    loss = torch.tensor([[2.5]])
    kl = torch.tensor([[1.2]])
    rewards = torch.tensor([3.0, 4.0, 5.0])

    return agent, loss, kl, rewards


def mock_gather_tensor(tensor, agent):
    if not isinstance(tensor, torch.Tensor):
        tensor = torch.tensor(tensor, device=f"cuda:{agent.local_rank}")
    tensor = tensor.detach().clone()
    world_size = agent.world_size
    gathered_tensors = []
    for i in range(world_size):
        gathered_tensors.append(tensor)
    return torch.stack(gathered_tensors)


@patch("agilerl.utils.utils.gather_tensor", side_effect=mock_gather_tensor)
def test_basic_aggregation(mock_gather, setup_test_data):
    """Test basic aggregation functionality."""
    agent, *data = setup_test_data
    avg_loss, avg_kl, avg_reward = (
        aggregate_metrics_across_gpus(agent, metric) for metric in data
    )
    mock_gather.assert_called()
    assert avg_loss == 2.5
    assert pytest.approx(avg_kl) == 1.2
    assert avg_reward == 4.0
    assert mock_gather.call_count == 3
    mock_gather.assert_any_call(data[0], agent)
    mock_gather.assert_any_call(data[1], agent)
    assert mock_gather.call_args_list[2][0][0].mean() == 4.0


def test_save_with_accelerator():
    """Test saving checkpoint when agent has an accelerator."""
    agent = Mock()
    agent.actor = Mock()
    agent.accelerator = Mock()
    agent.algo = "grpo"
    unwrapped_model = Mock()
    agent.accelerator.unwrap_model = Mock(return_value=unwrapped_model)
    save_llm_checkpoint(agent, "test_checkpoint")
    agent.accelerator.unwrap_model.assert_called_once_with(agent.actor)
    unwrapped_model.save_pretrained.assert_called_once_with("test_checkpoint/grpo")


def test_save_without_accelerator():
    """Test saving checkpoint when agent has no accelerator."""
    agent = Mock()
    agent.actor = Mock()
    agent.algo = "grpo"
    agent.accelerator = None
    save_llm_checkpoint(agent, None)
    agent.actor.save_pretrained.assert_called_once_with("./saved_checkpoints/grpo")
