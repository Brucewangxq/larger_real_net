"""
Main function for training and evaluating agents in traffic envs
@author: Tianshu Chu
"""
import argparse
import configparser
import logging
import tensorflow as tf
import threading
from envs.test_env import GymEnv
#from envs.small_grid_env import SmallGridEnv, SmallGridController
#from envs.large_grid_env import LargeGridEnv, LargeGridController
from envs.large_grid_env_larger import LargeGridEnv, LargeGridController
#from envs.real_net_env import RealNetEnv, RealNetController
from agents.models import A2C, IA2C, MA2C, IQL
from agents.q_learning import DQN, MFQ
from agents.ddpg_ensemble import DDPGEN
#from agents.dq_learning import DDQN
from utils import (Counter, Trainer, Tester, Evaluator,
                   check_dir, copy_file, find_file,
                   init_dir, init_log, init_test_flag,
                   plot_evaluation, plot_train)

def parse_args():
    #default_base_dir = './large_network_larger/ma2c' # need modify, for different alogrithms to evaluate
    default_base_dir = './large_network_larger/ddpg'  #greedy, codql, ma2c, dqn #need modify, for different alogrithms to train
    default_config_dir = './config/config_ddpg_large.ini' #greedy, codql, ma2c, dqn# need modify, for different alogrithms
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-dir', type=str, required=False,
                        default=default_base_dir, help="experiment base dir")
    subparsers = parser.add_subparsers(dest='option', help="train or evaluate")
    sp = subparsers.add_parser('train', help='train a single agent under base dir')
    sp.add_argument('--test-mode', type=str, required=False,
                    default='no_test',
                    help="test mode during training",
                    choices=['no_test', 'in_train_test', 'after_train_test', 'all_test'])
    sp.add_argument('--config-dir', type=str, required=False,
                    default=default_config_dir, help="experiment config path")
    sp = subparsers.add_parser('evaluate', help="evaluate and compare agents under base dir")
    sp.add_argument('--agents', type=str, required=False,
                    default='naive', help="agent folder names for evaluation, split by ,")
    sp.add_argument('--evaluate-seeds', type=str, required=False,
                    default=','.join([str(i) for i in range(10000, 100001, 10000)]),
                    help="random seeds for evaluation, split by ,")
    sp.add_argument('--demo', action='store_true', help="shows SUMO gui")
    args = parser.parse_args()
    if not args.option:
        parser.print_help()
        exit(1)
    return args

def init_env(config, port=0, naive_policy=False):
    if config.get('scenario') == 'large_grid':
        if not naive_policy:
            return LargeGridEnv(config, port=port)
        else:
            env = LargeGridEnv(config, port=port)
            policy = LargeGridController(env.node_names)
            return env, policy
    elif config.get('scenario') in ['Acrobot-v1', 'CartPole-v0', 'MountainCar-v0']:
        return GymEnv(config.get('scenario'))
    else:
        if not naive_policy:
            return None
        else:
            return None, None

def train(args):
    base_dir = args.base_dir
    dirs = init_dir(base_dir)
    init_log(dirs['log'])
    config_dir = args.config_dir
    copy_file(config_dir, dirs['data'])
    config = configparser.ConfigParser()
    config.read(config_dir)
    in_test, post_test = init_test_flag(args.test_mode)

    # init env
    env = init_env(config['ENV_CONFIG'])
    logging.info('Training: s dim: %d, a dim %d, s dim ls: %r, a dim ls: %r' %
                 (env.n_s, env.n_a, env.n_s_ls, env.n_a_ls))

    # init step counter
    total_step = int(config.getfloat('TRAIN_CONFIG', 'total_step')) #1e6
    test_step = int(config.getfloat('TRAIN_CONFIG', 'test_interval')) #2e4
    log_step = int(config.getfloat('TRAIN_CONFIG', 'log_interval')) #1e4
    global_counter = Counter(total_step, test_step, log_step)

    # init centralized or multi agent
    seed = config.getint('ENV_CONFIG', 'seed') #12
    # coord = tf.train.Coordinator()

    if env.agent == 'ia2c':
        model = IA2C(env.n_s_ls, env.n_a_ls, env.n_w_ls, total_step,
                     config['MODEL_CONFIG'], seed=seed)
    elif env.agent == 'ma2c':
        model = MA2C(env.n_s_ls, env.n_a_ls, env.n_w_ls, env.n_f_ls, total_step,
                     config['MODEL_CONFIG'], seed=seed)
    elif env.agent == 'codql':
        print('This is codql')
        num_agents = len(env.n_s_ls)
        print('num_agents:',num_agents)
        a_dim = env.n_a_ls[0] # ?????????????????? dim ??or num??
        print('a_dim:',a_dim)
        s_dim = env.n_s_ls[0]
        print('env.n_s_ls=', s_dim)
        s_dim_wait = env.n_w_ls[0]
        print('s_dim_wait:',s_dim_wait)
        #obs_space = s_dim # XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXxx state dim Error
        model = MFQ(nb_agent=num_agents, a_dim=a_dim, s_dim=s_dim, s_dim_wave=s_dim-s_dim_wait, s_dim_wait=s_dim_wait, 
                    config=config['MODEL_CONFIG'])
    elif env.agent == 'dqn':
        model = DQN(nb_agent=len(env.n_s_ls), a_dim=env.n_a_ls[0], s_dim=env.n_s_ls[0], 
                    s_dim_wave=env.n_s_ls[0] - env.n_w_ls[0], s_dim_wait=env.n_w_ls[0],
                    config=config['MODEL_CONFIG'], doubleQ=False) #doubleQ=False denotes dqn else ddqn
    elif env.agent == 'ddpg':
        model = DDPGEN(nb_agent=len(env.n_s_ls), share_params=True, a_dim=env.n_a_ls[0],
                       s_dim=env.n_s_ls[0], s_dim_wave=env.n_s_ls[0]-env.n_w_ls[0], s_dim_wait=env.n_w_ls[0])
    elif env.agent == 'iqld':
        model = IQL(env.n_s_ls, env.n_a_ls, env.n_w_ls, total_step, config['MODEL_CONFIG'],
                    seed=0, model_type='dqn')
    else:
        model = IQL(env.n_s_ls, env.n_a_ls, env.n_w_ls, total_step, config['MODEL_CONFIG'],
                    seed=0, model_type='lr')

    summary_writer = tf.summary.FileWriter(dirs['log'])
    trainer = Trainer(env, model, global_counter, summary_writer, in_test, output_path=dirs['data'])
    trainer.run()

    # save model
    final_step = global_counter.cur_step
    logging.info('Training: save final model at step %d ...' % final_step)
    model.save(dirs['model'], final_step)

def evaluate_fn(agent_dir, output_dir, seeds, port, demo):
    agent = agent_dir.split('/')[-1]
    doubleQ = True
    if agent=='ddqn':
        doubleQ = False
        agent='dqn'
    if not check_dir(agent_dir):
        logging.error('Evaluation: %s does not exist!' % agent)
        return
    # load config file for env
    config_dir = find_file(agent_dir + '/data/')
    if not config_dir:
        return
    config = configparser.ConfigParser()
    config.read(config_dir)

    # init env
    env, greedy_policy = init_env(config['ENV_CONFIG'], port=port, naive_policy=True)
    logging.info('Evaluation: s dim: %d, a dim %d, s dim ls: %r, a dim ls: %r' %
                 (env.n_s, env.n_a, env.n_s_ls, env.n_a_ls))
    env.init_test_seeds(seeds)

    # load model for agent
    if agent != 'greedy':
        # init centralized or multi agent
        if agent == 'a2c':
            model = A2C(env.n_s, env.n_a, 0, config['MODEL_CONFIG'])
        elif agent == 'ia2c':
            model = IA2C(env.n_s_ls, env.n_a_ls, env.n_w_ls, 0, config['MODEL_CONFIG'])
        elif agent == 'ma2c':
            model = MA2C(env.n_s_ls, env.n_a_ls, env.n_w_ls, env.n_f_ls, 0, config['MODEL_CONFIG'])
        elif agent == 'codql':
            print('This is codql')
            model = MFQ(nb_agent=len(env.n_s_ls), a_dim=env.n_a_ls[0], s_dim=env.n_s_ls[0], 
                        s_dim_wave=env.n_s_ls[0] - env.n_w_ls[0],
                        s_dim_wait=env.n_w_ls[0], config=config['MODEL_CONFIG'])
        elif agent == 'dqn':
            model = DQN(nb_agent=len(env.n_s_ls), a_dim=env.n_a_ls[0], s_dim=env.n_s_ls[0],
                        s_dim_wave=env.n_s_ls[0] - env.n_w_ls[0], s_dim_wait=env.n_w_ls[0],
                        config=config['MODEL_CONFIG'],doubleQ=doubleQ) #doubleQ=False denotes dqn else ddqn
        elif agent == 'ddpg':
            model = DDPGEN(nb_agent=len(env.n_s_ls), share_params=True, a_dim=env.n_a_ls[0],
                       s_dim=env.n_s_ls[0], s_dim_wave=env.n_s_ls[0]-env.n_w_ls[0], s_dim_wait=env.n_w_ls[0])
        elif agent == 'iqld':
            model = IQL(env.n_s_ls, env.n_a_ls, env.n_w_ls, 0, config['MODEL_CONFIG'],
                        seed=0, model_type='dqn')
        else:
            model = IQL(env.n_s_ls, env.n_a_ls, env.n_w_ls, 0, config['MODEL_CONFIG'],
                        seed=0, model_type='lr')
        if not model.load(agent_dir + '/model/'):
            return
    else:
        model = greedy_policy
    env.agent = agent
    # collect evaluation data
    evaluator = Evaluator(env, model, output_dir, demo=demo)
    evaluator.run()

def evaluate(args):
    base_dir = args.base_dir
    dirs = init_dir(base_dir, pathes=['eva_data', 'eva_log'])
    init_log(dirs['eva_log'])
    #agents = args.agents.split(',')
    # enforce the same evaluation seeds across agents
    seeds = args.evaluate_seeds
    logging.info('Evaluation: random seeds: %s' % seeds)
    if not seeds:
        seeds = []
    else:
        seeds = [int(s) for s in seeds.split(',')]
    evaluate_fn(base_dir, dirs['eva_data'], seeds, 0, args.demo)
    #threads = []
    #for i, agent in enumerate(agents):
    #    agent_dir = base_dir + '/' + agent
    #    thread = threading.Thread(target=evaluate_fn,
    #                              args=(agent_dir, dirs['eva_data'], seeds, i, args.demo))
    #    thread.start()
    #    threads.append(thread)
    #for thread in threads:
    #    thread.join()

if __name__ == '__main__':
    args = parse_args()
    if args.option == 'train':
        train(args) #main.py train
    else:
        evaluate(args) #main.py evaluate --agents
