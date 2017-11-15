import os
import numpy as np
from datetime import datetime
from warnings import warn

import nengo
from nengo.spa.module import Module
from nengo.utils.network import with_self

from ..vocabs import vis_vocab, mtr_vocab
from .vision import get_image as vis_get_image
from .vision import get_image_label


num_map = {'0': 'ZER', '1': 'ONE', '2': 'TWO', '3': 'THR', '4': 'FOR',
           '5': 'FIV', '6': 'SIX', '7': 'SEV', '8': 'EIG', '9': 'NIN'}
sym_map = {'[': 'OPEN', ']': 'CLOSE', '?': 'QM'}

num_rev_map = {}
for key in num_map.keys():
    num_rev_map[num_map[key]] = key
sym_rev_map = {}
for key in sym_map.keys():
    sym_rev_map[sym_map[key]] = key

num_out_list = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '-']


# Wrapper function for vision get_image function to pass config rng.
def get_image(label=None):
    return vis_get_image(label, cfg.rng)


def get_vocab(label=None):
    if label is None:
        return (np.zeros(cfg.sp_dim), -1)
    if isinstance(label, tuple):
        label = num_map[label[1]]

    return (vis_vocab[str(label)].v, 0)


def insert_mtr_wait_sym(num_mtr_responses):
    # Add 0.5 second motor response minimum
    num_mtr_responses += 0.5
    est_mtr_response_time = num_mtr_responses * cfg.mtr_est_digit_response_time
    extra_spaces = int(est_mtr_response_time / (cfg.present_interval * 2 **
                                                cfg.present_blanks))

    cfg.raw_seq.extend([None] * extra_spaces)


def parse_mult_seq(seq_str):
    mult_open_ind = seq_str.find('{')
    mult_close_ind = seq_str.find('}')
    mult_value_ind = seq_str.find(':')

    if mult_open_ind >= 0 and mult_close_ind >= 0 and mult_value_ind >= 0:
        return parse_mult_seq(seq_str[:mult_open_ind] +
                              parse_mult_seq(seq_str[mult_open_ind + 1:]))
    elif (mult_close_ind >= 0 and mult_value_ind >= 0 and
          mult_value_ind < mult_close_ind):
        return (seq_str[:mult_value_ind] *
                int(seq_str[mult_value_ind + 1:mult_close_ind]) +
                seq_str[mult_close_ind + 1:])
    elif mult_open_ind == mult_close_ind == mult_value_ind == -1:
        return seq_str
    else:
        raise ValueError('Invalid multiplicative indicator format.')


def parse_custom_tasks(seq_str):
    task_open_ind = seq_str.find('(')
    task_close_ind = -1
    rslt_str = ""

    while task_open_ind >= 0:
        rslt_str += seq_str[task_close_ind + 1: task_open_ind]

        task_opts_ind = seq_str.find(';', task_open_ind)
        task_close_ind = seq_str.find(')', task_open_ind)

        if (task_opts_ind < 0 or task_close_ind < 0) or \
           (task_close_ind < task_opts_ind):
            raise ValueError('Malformed custom task string.')

        task_str = seq_str[task_open_ind + 1:task_opts_ind]
        task_opts_str = seq_str[task_opts_ind + 1:task_close_ind]

        if task_str == "COUNT":
            # Format: (COUNT; NUMCOUNT)
            count_val = int(task_opts_str)
            start_val = int(np.random.random() * (len(num_map) - count_val))
            new_task_str = 'A4[%d][%d]' % (start_val, count_val)
        elif task_str == "LEARN":
            # Format: (LEARN; PROB1, NUMTRIALS1; PROB2, NUMTRAILS2; ...)
            learn_opts = task_opts_str.split(';')
            num_trials = len(learn_opts)
            new_task_str = 'A2?' + 'X?' * num_trials + 'X'
        else:
            raise ValueError('Custom task string "%s" ' % task_str +
                             'not supported.')

        rslt_str += new_task_str
        task_open_ind = seq_str.find('(', task_open_ind + 1)

    return rslt_str + seq_str[task_close_ind + 1:]


def parse_raw_seq():
    raw_seq = parse_custom_tasks(parse_mult_seq(cfg.raw_seq_str))
    hw_num = False  # Flag to indicate to use a hand written number
    fixed_num = False

    prev_c = ''
    fixed_c = ''
    value_maps = {}

    num_n = 0
    num_r = 0

    cfg.raw_seq = []
    cfg.stim_seq = []

    num_mtr_responses = 0.0

    for c in raw_seq:
        if c == 'N':
            num_n += 1
            continue
        else:
            cs = np.random.choice(num_map.keys(), num_n, replace=False)
            for n in cs:
                cfg.raw_seq.append(n)
            num_n = 0

        if c == 'R':
            num_r += 1
            continue
        else:
            cs = np.random.choice(num_map.keys(), num_r, replace=True)
            for r in cs:
                cfg.raw_seq.append(r)
            num_r = 0

        if c == 'A':    # Clear the value maps for each task
            value_maps = {}
            num_n = 0
            num_r = 0

        if c.islower():
            if c not in value_maps:
                value_maps[c] = np.random.choice(num_map.keys(), 1,
                                                 replace=True)[0]
            c = value_maps[c]

        if c == 'X':
            num_mtr_responses += 1
            continue
        elif num_mtr_responses > 0:
            insert_mtr_wait_sym(num_mtr_responses)
            num_mtr_responses = 0

        cfg.raw_seq.append(c)

    # Insert trailing motor response wait symbols
    insert_mtr_wait_sym(num_mtr_responses)

    for c in cfg.raw_seq:
        if c == '#':
            hw_num = True
            continue

        if fixed_num:
            if (not c.isdigit() and c not in ['>']) or \
               (c == '>' and len(fixed_c) <= 0):
                raise ValueError('Malformed fixed index number string.')
            elif c.isdigit():
                fixed_c += c
                continue

        if c == '<':
            fixed_num = True
            fixed_c = ''
            continue

        if c in sym_map:
            c = sym_map[c]
        if not hw_num and c in num_map:
            c = num_map[c]

        # If previous character is identical to current character, insert a
        # space between them.
        if c is not None and prev_c == c and not cfg.present_blanks:
            cfg.stim_seq.append('.')

        if c is not None and c.isdigit() and hw_num:
            img_ind = get_image(c)[1]
            cfg.stim_seq.append((img_ind, c))
            c = img_ind
            hw_num = False
        elif c is not None and c == '>' and fixed_num:
            cfg.stim_seq.append((int(fixed_c),
                                 str(get_image_label(int(fixed_c)))))
            fixed_num = False
        else:
            cfg.stim_seq.append(c)

        prev_c = c


def stim_func(t, stim_seq=None, get_func=None):
    ind = t / cfg.present_interval / (2 ** cfg.present_blanks)

    if (cfg.present_blanks and int(ind) != int(round(ind))) or \
       int(ind) >= len(stim_seq) or stim_seq[int(ind)] == '.':
        image_data = get_func()
    else:
        image_data = get_func(stim_seq[int(ind)])

    return image_data[0]


def stim_func_vis(t):
    return stim_func(t, cfg.stim_seq, get_image)


def stim_func_vocab(t):
    return stim_func(t, cfg.stim_seq, get_vocab)


def get_est_runtime():
    return len(cfg.stim_seq) * cfg.present_interval * (2 ** cfg.present_blanks)


class Stimulus(Module):
    def __init__(self, cfg, label="Stimulus", seed=None, add_to_container=None):
        self.cfg = cfg
        super(Stimulus, self).__init__(label, seed, add_to_container)
        self.init_module()

    @with_self
    def init_module(self):
        if self.cfg.use_mpi:
            import nengo_mpi

            dimension = get_image()[0].size
            self.output = \
                nengo_mpi.SpaunStimulus(dimension, self.cfg.raw_seq,
                                        self.cfg.present_interval,
                                        self.cfg.present_blanks)
        else:
            self.output = nengo.Node(output=stim_func_vis,
                                     label='Stim Module Out')

        # Define vocabulary inputs and outputs
        self.outputs = dict(default=(self.output, vis_vocab))


class StimulusDummy(Module):
    def __init__(self, label="Stimulus", seed=None, add_to_container=None):
        super(StimulusDummy, self).__init__(label, seed, add_to_container)
        self.init_module()

    @with_self
    def init_module(self):
        dimension = 28 * 28
        self.output = nengo.Node(output=np.random.uniform(size=dimension))

        # Define vocabulary inputs and outputs
        self.outputs = dict(default=(self.output, vis_vocab))


class MonitorData(object):
    def __init__(self, cfg):
        self.cfg = cfg
        self.data_filename = \
            os.path.join(self.cfg.data_dir,
                         self.cfg.probe_data_filename[:-4] + '_log.txt')
        self.data_obj = open(self.data_filename, 'a')

        self.prev_ind = -1
        self.mtr_written = False
        self.mtr_write_min = 0.75
        self.mtr_reset_max = 0.25
        self.null_output = "_"

        self.write_header()

    def write_header(self):
        self.data_obj.write('# Spaun Simulation Properties:\n')
        self.data_obj.write('# - Run datetime: %s\n' % datetime.now())
        self.data_obj.write('# Spaun Configuration Options:\n')
        self.data_obj.write('# ----------------------------\n')
        for param_name in sorted(self.cfg.__dict__.keys()):
            if not callable(getattr(self.cfg, param_name)):
                self.data_obj.write('# - %s = %s\n' %
                                    (param_name, getattr(self.cfg, param_name)))
        self.data_obj.write('# ----------------------------\n')

    def write_to_file(self, str):
        orig_closed_state = self.data_obj.closed
        if orig_closed_state:
            self.data_obj = open(self.data_filename, 'a')

        self.data_obj.write(str)

        if orig_closed_state:
            self.data_obj.close()

    def close_data_obj(self):
        self.data_obj.close()


class Monitor(Module):
    def __init__(self, cfg, label="Monitor", seed=None, add_to_container=None):
        super(Monitor, self).__init__(label, seed, add_to_container)
        self.cfg = cfg
        self.monitor_data = MonitorData(self.cfg)
        self.init_module()

    @with_self
    def init_module(self):
        if self.cfg.use_mpi:
            raise RuntimeError('Not Implemented')
        else:
            self.output = \
                nengo.Node(output=self.make_node_func(),
                           size_in=len(mtr_vocab.keys) + 3,
                           label='Experiment monitor')

        # Define vocabulary inputs and outputs
        self.outputs = dict(default=(self.output, vis_vocab))

    def make_node_func(self):

        def monitor_func(t, x, monitor=self.monitor_data, stim_seq=self.cfg.stim_seq):
            ind = t / self.cfg.present_interval / (2 ** self.cfg.present_blanks)
            eff_ind = int(ind)

            if (eff_ind != monitor.prev_ind and eff_ind < len(stim_seq)):
                stim_char = stim_seq[eff_ind]
                if (stim_char == '.'):
                    monitor.write_to_file('_')
                    # print '_', eff_ind, monitor.prev_ind
                elif stim_char == 'A' and monitor.prev_ind >= 0:
                    monitor.write_to_file('\nA')
                    # print '\nA', eff_ind, monitor.prev_ind
                elif isinstance(stim_char, int):
                    monitor.write_to_file('<%s>' % stim_char)
                    # print "<", stim_char, ">", eff_ind, monitor.prev_ind
                elif stim_char in num_rev_map:
                    monitor.write_to_file('%s' % num_rev_map[stim_char])
                    # print num_rev_map[stim_char], eff_ind, monitor.prev_ind
                elif stim_char in sym_rev_map:
                    monitor.write_to_file('%s' % sym_rev_map[stim_char])
                    # print sym_rev_map[stim_char], eff_ind, monitor.prev_ind
                elif stim_char is not None:
                    monitor.write_to_file('%s' % str(stim_char))
                    # print stim_char, eff_ind, monitor.prev_ind

                if self.cfg.present_blanks and stim_char is not None:
                    monitor.write_to_file('_')
                    # print ' ', eff_ind, monitor.prev_ind
                monitor.prev_ind = eff_ind
                monitor.data_obj.flush()

            # Determine what has been written
            write_inds = x[:-2]
            write_out_ind = int(np.sum(np.where(write_inds > 0.5)))
            if write_out_ind >= 0 and write_out_ind < len(num_out_list):
                write_out = num_out_list[write_out_ind]
            else:
                write_out = monitor.null_output

            mtr_ramp = x[-2]
            mtr_disable = x[-1]

            if mtr_disable < 0.5:
                if mtr_ramp > monitor.mtr_write_min and not monitor.mtr_written:
                    monitor.write_to_file(write_out)
                    monitor.mtr_written = True
                    monitor.data_obj.flush()
                elif mtr_ramp < monitor.mtr_reset_max:
                    monitor.mtr_written = False

        return monitor_func

    def setup_connections(self, parent_net):
        # Set up connections from dec module
        if hasattr(parent_net, 'dec'):
            nengo.Connection(parent_net.dec.dec_ind_output, self.output[:-2],
                             synapse=0.05)
        else:
            warn("Monitor Module - Cannot connect from 'dec'")

        # Set up connections from motor module
        if hasattr(parent_net, 'mtr'):
            nengo.Connection(parent_net.mtr.ramp, self.output[-2],
                             synapse=0.05)
            # TODO: Include connection that inhibits motor output
        else:
            warn("Monitor Module - Cannot connect from 'mtr'")

    def close(self):
        self.monitor_data.close_data_obj()
