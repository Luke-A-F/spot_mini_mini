import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
from torch.distributions import Normal
import copy

# alg specific imports
from .softQnetwork import SoftQNetwork
from .valuenetwork import ValueNetwork

# device
device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")


class SoftActorCritic(object):
    def __init__(
            self,
            policy,
            state_dim,
            action_dim,
            replay_buffer,
            hidden_dim=256,
            value_lr=3e-4,
            soft_q_lr=3e-4,
            policy_lr=3e-4,
    ):

        # set up the networks
        self.value_net = ValueNetwork(state_dim, hidden_dim).to(device)
        self.target_value_net = copy.deepcopy(self.value_net)
        self.policy_net = policy.to(device)

        self.soft_q_net = SoftQNetwork(state_dim, action_dim,
                                       hidden_dim).to(device)

        # copy the target params over
        for target_param, param in zip(self.target_value_net.parameters(),
                                       self.value_net.parameters()):
            target_param.data.copy_(param.data)

        # set the losses
        self.value_criterion = nn.MSELoss()
        self.soft_q_criterion = nn.MSELoss()

        # set the optimizers
        self.value_optimizer = optim.Adam(self.value_net.parameters(),
                                          lr=value_lr)
        self.soft_q_optimizer = optim.Adam(self.soft_q_net.parameters(),
                                           lr=soft_q_lr)
        self.policy_optimizer = optim.Adam(self.policy_net.parameters(),
                                           lr=policy_lr)

        # reference the replay buffer
        self.replay_buffer = replay_buffer

        self.log = {'value_loss': [], 'q_value_loss': [], 'policy_loss': []}

    def soft_q_update(self,
                      batch_size,
                      gamma=0.99,
                      mean_lambda=1e-3,
                      std_lambda=1e-3,
                      z_lambda=0.0,
                      soft_tau=1e-2):
        state, action, reward, next_state, done = self.replay_buffer.sample(
            batch_size)

        state = torch.FloatTensor(state).to(device)
        next_state = torch.FloatTensor(next_state).to(device)
        action = torch.FloatTensor(action).to(device)
        reward = torch.FloatTensor(reward).unsqueeze(1).to(device)
        done = torch.FloatTensor(np.float32(done)).unsqueeze(1).to(device)

        expected_q_value = self.soft_q_net(state, action)
        expected_value = self.value_net(state)
        new_action, log_prob, z, mean, log_std = self.policy_net.evaluate(
            state)

        target_value = self.target_value_net(next_state)
        next_q_value = reward + (1 - done) * gamma * target_value
        q_value_loss = self.soft_q_criterion(expected_q_value,
                                             next_q_value.detach())

        expected_new_q_value = self.soft_q_net(state, new_action)
        next_value = expected_new_q_value - log_prob
        value_loss = self.value_criterion(expected_value, next_value.detach())

        log_prob_target = expected_new_q_value - expected_value
        policy_loss = (log_prob * (log_prob - log_prob_target).detach()).mean()

        mean_loss = mean_lambda * mean.pow(2).mean()
        std_loss = std_lambda * log_std.pow(2).mean()
        z_loss = z_lambda * z.pow(2).sum(1).mean()

        policy_loss += mean_loss + std_loss + z_loss

        self.soft_q_optimizer.zero_grad()
        q_value_loss.backward()
        self.soft_q_optimizer.step()

        self.value_optimizer.zero_grad()
        value_loss.backward()
        self.value_optimizer.step()

        self.policy_optimizer.zero_grad()
        policy_loss.backward()
        self.policy_optimizer.step()

        for target_param, param in zip(self.target_value_net.parameters(),
                                       self.value_net.parameters()):
            target_param.data.copy_(target_param.data * (1.0 - soft_tau) +
                                    param.data * soft_tau)

        self.log['q_value_loss'].append(q_value_loss.item())
        self.log['value_loss'].append(value_loss.item())
        self.log['policy_loss'].append(policy_loss.item())

    def save(self, filename):
        torch.save(self.value_net.state_dict(), filename + "_value_net")
        torch.save(self.value_optimizer.state_dict(),
                   filename + "_value_optimizer")
        torch.save(self.policy_net.state_dict(), filename + "_policy_net")
        torch.save(self.policy_optimizer.state_dict(),
                   filename + "_policy_optimizer")
        torch.save(self.soft_q_net.state_dict(), filename + "_soft_q_net")
        torch.save(self.soft_q_optimizer.state_dict(),
                   filename + "_soft_q_optimizer")

    def load(self, filename):
        self.value_net.load_state_dict(
            torch.load(filename + "_value_net", map_location=device))
        self.value_optimizer.load_state_dict(
            torch.load(filename + "_value_optimizer",
                       map_location=device))
        self.policy_net.load_state_dict(
            torch.load(filename + "_policy_net", map_location=device))
        self.policy_optimizer.load_state_dict(
            torch.load(filename + "_policy_optimizer",
                       map_location=device))
        self.soft_q_net.load_state_dict(
            torch.load(filename + "_soft_q_net", map_location=device))
        self.soft_q_optimizer.load_state_dict(
            torch.load(filename + "_soft_q_optimizer",
                       map_location=device))
