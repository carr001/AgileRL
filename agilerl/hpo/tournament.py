from typing import List, Tuple

import numpy as np

from agilerl.algorithms.core.base import EvolvableAlgorithm

PopulationType = List[EvolvableAlgorithm]


class TournamentSelection:
    """The tournament selection class.

    :param tournament_size: Tournament selection size
    :type tournament_size: int
    :param elitism: Elitism in tournament selection
    :type elitism: bool
    :param population_size: Number of agents in population
    :type population_size: int
    :param eval_loop: Number of most recent fitness scores to use in evaluation
    :type eval_loop: int
    """

    def __init__(
        self, tournament_size: int, elitism: bool, population_size: int, eval_loop: int
    ) -> None:
        assert tournament_size > 0, "Tournament size must be greater than zero."
        assert isinstance(elitism, bool), "Elitism must be boolean value True or False."
        assert population_size > 0, "Population size must be greater than zero."
        assert eval_loop > 0, "Evo step must be greater than zero."

        self.tournament_size = tournament_size
        self.elitism = elitism
        self.population_size = population_size
        self.eval_loop = eval_loop

    def _tournament(self, fitness_values: List[float]) -> int:
        """
        Perform a tournament selection.

        :param fitness_values: List of fitness values
        :type fitness_values: list[float]
        :return: Index of the selected winner
        :rtype: int
        """
        selection = np.random.randint(0, len(fitness_values), size=self.tournament_size)
        selection_values = [fitness_values[i] for i in selection]
        winner = selection[np.argmax(selection_values)]
        return winner

    def _elitism(
        self, population: PopulationType
    ) -> Tuple[EvolvableAlgorithm, np.ndarray, int]:
        """
        Perform elitism selection.

        :param population: Population of agents
        :type population: PopulationType
        :return: Elite member of population, rank array, and max id
        :rtype: tuple[EvolvableAlgorithm, np.ndarray, int]
        """
        last_fitness = [np.mean(indi.fitness[-self.eval_loop :]) for indi in population]
        rank = np.argsort(last_fitness).argsort()
        max_id = max([ind.index for ind in population])
        model = population[int(np.argsort(rank)[-1])]
        elite = model.clone()
        return elite, rank, max_id

    def select(
        self, population: PopulationType
    ) -> Tuple[EvolvableAlgorithm, PopulationType]:
        """
        Returns best agent and new population of agents following tournament selection.

        :param population: Population of agents
        :type population: PopulationType
        :return: Elite agent and new population
        :rtype: tuple[EvolvableAlgorithm, PopulationType]
        """
        elite, rank, max_id = self._elitism(population)

        new_population = []
        if self.elitism:  # keep top agent in population
            new_population.append(elite.clone(wrap=False))
            selection_size = self.population_size - 1
        else:
            selection_size = self.population_size

        # select parents of next gen using tournament selection
        for idx in range(selection_size):
            max_id += 1
            actor_parent = population[self._tournament(rank)]
            new_individual = actor_parent.clone(max_id, wrap=False)
            new_population.append(new_individual)

        return elite, new_population
