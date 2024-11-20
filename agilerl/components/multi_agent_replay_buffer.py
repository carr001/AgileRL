from typing import List, Optional, Tuple, Dict, Any, Deque, NamedTuple
import random
from collections import deque, namedtuple
import numpy as np
import torch


class MultiAgentReplayBuffer:
    """The Multi-Agent Experience Replay Buffer class. Used to store multiple agents'
    experiences and allow off-policy learning.

    :param memory_size: Maximum length of the replay buffer
    :type memory_size: int
    :param field_names: Field names for experience named tuple, e.g. ['state', 'action', 'reward']
    :type field_names: List[str]
    :param agent_ids: Names of all agents that will act in the environment
    :type agent_ids: List[str]
    :param device: Device for accelerated computing, 'cpu' or 'cuda', defaults to None
    :type device: Optional[str]
    """

    def __init__(self, memory_size: int, field_names: List[str], agent_ids: List[str], device: Optional[str] = None):
        assert memory_size > 0, "Memory size must be greater than zero."
        assert len(field_names) > 0, "Field names must contain at least one field name."
        assert len(agent_ids) > 0, "Agent ids must contain at least one agent id."

        self.memory_size: int = memory_size
        self.memory: Deque = deque(maxlen=memory_size)
        self.field_names: List[str] = field_names
        self.experience: NamedTuple = namedtuple("Experience", field_names=self.field_names)
        self.counter: int = 0
        self.device: Optional[str] = device
        self.agent_ids: List[str] = agent_ids

    def __len__(self) -> int:
        """
        Returns the current size of internal memory.

        :return: Length of the memory
        :rtype: int
        """
        return len(self.memory)

    def _add(self, *args: Any) -> None:
        """
        Adds experience to memory.

        :param args: Variable length argument list for experience fields
        :type args: Any
        """
        e = self.experience(*args)
        self.memory.append(e)

    def _process_transition(self, experiences: List[NamedTuple], np_array: bool = False) -> Dict[str, Dict[str, Any]]:
        """
        Returns transition dictionary from experiences.

        :param experiences: List of experiences
        :type experiences: List[NamedTuple]
        :param np_array: Flag to return numpy arrays instead of tensors, defaults to False
        :type np_array: bool, optional
        :return: Transition dictionary
        :rtype: Dict[str, Dict[str, Any]]
        """
        transition = {field: {} for field in self.field_names}
        experiences_filtered = [e for e in experiences if e is not None]

        for field in self.field_names:
            is_binary_field = field in [
                "done",
                "termination",
                "terminated",
                "truncation",
                "truncated",
            ]

            for agent_id in self.agent_ids:
                ts = np.array(
                    [getattr(e, field)[agent_id] for e in experiences_filtered]
                )

                if ts.ndim == 1:
                    ts = np.expand_dims(ts, axis=1)

                if is_binary_field:
                    ts = ts.astype(np.uint8)

                if not np_array:
                    ts = torch.tensor(ts, dtype=torch.float32)
                    if self.device is not None:
                        ts = ts.to(self.device)

                transition[field][agent_id] = ts

        return transition

    def sample(self, batch_size: int, *args: Any) -> Tuple:
        """
        Returns sample of experiences from memory.

        :param batch_size: Number of samples to return
        :type batch_size: int
        :param args: Additional arguments
        :type args: Any
        :return: Sampled experiences
        :rtype: Tuple
        """
        experiences = random.sample(self.memory, k=batch_size)
        transition = self._process_transition(experiences)
        return tuple(transition.values())

    def save_to_memory_single_env(self, *args: Any) -> None:
        """
        Saves experience to memory.

        :param args: Variable length argument list. Contains transition elements in consistent order,
            e.g. state, action, reward, next_state, done
        :type args: Any
        """
        self._add(*args)
        self.counter += 1

    def _reorganize_dicts(self, *args: Dict[str, np.ndarray]) -> Tuple[List[Dict[str, np.ndarray]], ...]:
        """
        Reorganizes dictionaries from vectorized to unvectorized experiences.

        :param args: Variable length argument list of dictionaries
        :type args: Dict[str, np.ndarray]
        :return: Reorganized dictionaries
        :rtype: Tuple[List[Dict[str, np.ndarray]], ...]
        """
        results = [[] for _ in range(len(args))]
        num_entries = len(next(iter(args[0].values())))
        for i in range(num_entries):
            for j, arg in enumerate(args):
                new_dict = {
                    key: (
                        np.array(value[i])
                        if not isinstance(value[i], np.ndarray)
                        else value[i]
                    )
                    for key, value in arg.items()
                }
                results[j].append(new_dict)
        return tuple(results)

    def save_to_memory_vect_envs(self, *args: Any) -> None:
        """
        Saves multiple experiences to memory.

        :param args: Variable length argument list. Contains batched transition elements in consistent order,
            e.g. states, actions, rewards, next_states, dones
        :type args: Any
        """
        args = self._reorganize_dicts(*args)
        for transition in zip(*args):
            self._add(*transition)
            self.counter += 1

    def save_to_memory(self, *args: Any, is_vectorised: bool = False) -> None:
        """
        Applies appropriate save_to_memory function depending on whether
        the environment is vectorized or not.

        :param args: Variable length argument list. Contains batched or unbatched transition elements in consistent order,
            e.g. states, actions, rewards, next_states, dones
        :type args: Any
        :param is_vectorised: Boolean flag indicating if the environment has been vectorized
        :type is_vectorised: bool
        """
        if is_vectorised:
            self.save_to_memory_vect_envs(*args)
        else:
            self.save_to_memory_single_env(*args)
