Training
=========

If you are using a Gym-style environment, it is easiest to use our training function, which returns a population of trained agents and logged training metrics.

If you are training on static, offline data, you can use our offline RL training function.

The multi agent training function handles Pettingzoo-style environments and multi-agent algorithms.

.. autofunction:: agilerl.training.train_off_policy.train_off_policy

.. autofunction:: agilerl.training.train_offline.train_offline

.. autofunction:: agilerl.training.train_on_policy.train_on_policy

.. autofunction:: agilerl.training.train_multi_agent_off_policy.train_multi_agent_off_policy
