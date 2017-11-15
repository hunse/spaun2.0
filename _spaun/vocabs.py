import os
import numpy as np

from nengo.spa import Vocabulary
# from ._spa import Vocabulary
from ._networks import convert_func_2_diff_func

from .utils import strs_to_inds


class Vocabs(object):
    def __init__(self, cfg):
        # ############### Semantic pointer (strings) definitions ######################
        # --- Numerical semantic pointers ---
        num_sp_strs = ['ZER', 'ONE', 'TWO', 'THR', 'FOR',
                       'FIV', 'SIX', 'SEV', 'EIG', 'NIN']
        n_num_sp = len(num_sp_strs)

        # --- Task semantic pointer list ---
        # W - Drawing (Copying visual input)
        # R - Recognition
        # L - Learning (Bandit Task)
        # M - Memory (forward serial recall)
        # C - Counting
        # A - Answering
        # V - Rapid Variable Creation
        # F - Fluid Induction (Ravens)
        # X - Task precursor
        # DEC - Decoding task (output to motor system)
        ps_task_sp_strs = ['W', 'R', 'L', 'M', 'C', 'A', 'V', 'F', 'X', 'DEC']
        ps_task_vis_sp_strs = ['A', 'C', 'F', 'K', 'L', 'M', 'P', 'R', 'V', 'W']

        # --- Production system semantic pointers ---
        # DECW - Decoding state (output to motor system, but for drawing task)
        # DECI - Decoding state (output to motor system, but for induction tasks)
        ps_state_sp_strs = ['QAP', 'QAK', 'TRANS0', 'TRANS1', 'TRANS2', 'CNT0', 'CNT1']
        ps_dec_sp_strs = ['FWD', 'REV', 'CNT', 'DECW', 'DECI']

        # --- Misc visual semantic pointers ---
        misc_vis_sp_strs = ['OPEN', 'CLOSE', 'SPACE', 'QM']

        # --- Misc state semantic pointers ---
        misc_ps_sp_strs = ['MATCH', 'NO_MATCH']

        # --- 'I don't know' motor response vector
        mtr_sp_strs = ['UNK']

        # --- List of all visual semantic pointers ---
        vis_sp_strs = list(num_sp_strs)
        vis_sp_strs.extend(misc_vis_sp_strs)
        vis_sp_strs.extend(ps_task_vis_sp_strs)

        # --- Position (enumerated) semantic pointers ---
        pos_sp_strs = ['POS%i' % (i + 1) for i in range(cfg.max_enum_list_pos)]

        # --- Operations semantic pointers
        ops_sp_strs = ['ADD', 'INC']

        # --- Unitary semantic pointers
        unitary_sp_strs = [num_sp_strs[0], pos_sp_strs[0]]
        unitary_sp_strs.extend(ops_sp_strs)


        # ####################### Vocabulary definitions ##############################
        # --- Primary vocabulary ---
        vocab = Vocabulary(cfg.sp_dim, unitary=unitary_sp_strs, rng=cfg.rng)
        self.vocab = vocab

        # --- Add numerical sp's ---
        vocab.parse('%s+%s' % (ops_sp_strs[0], num_sp_strs[0]))
        add_sp = vocab[ops_sp_strs[0]]
        num_sp = vocab[num_sp_strs[0]].copy()
        for i in range(len(num_sp_strs) - 1):
            num_sp = num_sp.copy() * add_sp
            vocab.add(num_sp_strs[i + 1], num_sp)

        # --- Add positional sp's ---
        vocab.parse('%s+%s' % (ops_sp_strs[1], pos_sp_strs[0]))
        inc_sp = vocab[ops_sp_strs[1]]
        pos_sp = vocab[pos_sp_strs[0]].copy()
        for i in range(len(pos_sp_strs) - 1):
            pos_sp = pos_sp.copy() * inc_sp
            vocab.add(pos_sp_strs[i + 1], pos_sp)

        # --- Add other visual sp's ---
        vocab.parse('+'.join(misc_vis_sp_strs))
        vocab.parse('+'.join(ps_task_vis_sp_strs))

        # --- Add production system sp's ---
        vocab.parse('+'.join(ps_task_sp_strs))
        vocab.parse('+'.join(ps_state_sp_strs))
        vocab.parse('+'.join(ps_dec_sp_strs))
        vocab.parse('+'.join(misc_ps_sp_strs))

        # ####################### Motor vocabularies ##################################
        mtr_filepath = os.path.join('_spaun', 'modules', 'motor')
        mtr_canon_paths = np.load(os.path.join(mtr_filepath, 'canon_paths.npz'))
        mtr_canon_paths_x = mtr_canon_paths['canon_paths_x']
        mtr_canon_paths_y = mtr_canon_paths['canon_paths_y']

        cfg.mtr_dim = mtr_canon_paths_x.shape[1] + mtr_canon_paths_y.shape[1]


        def make_mtr_sp(path_x, path_y):
            path_x = convert_func_2_diff_func(path_x)
            path_y = convert_func_2_diff_func(path_y)
            return np.concatenate((path_x, path_y))

        mtr_vocab = Vocabulary(cfg.mtr_dim, rng=cfg.rng)
        for i, sp_str in enumerate(num_sp_strs):
            mtr_sp_vec = make_mtr_sp(mtr_canon_paths_x[i, :], mtr_canon_paths_y[i, :])
            mtr_vocab.add(sp_str, mtr_sp_vec)

        mtr_unk_vocab = Vocabulary(cfg.mtr_dim, rng=cfg.rng)
        mtr_unk_vocab.add(mtr_sp_strs[0], make_mtr_sp(mtr_canon_paths_x[-1, :],
                                                      mtr_canon_paths_y[-1, :]))

        mtr_disp_vocab = mtr_vocab.create_subset(num_sp_strs)
        mtr_disp_vocab.readonly = False  # Disable read-only flag for display vocab
        mtr_disp_vocab.add(mtr_sp_strs[0], mtr_unk_vocab[mtr_sp_strs[0]].v)

        mtr_sp_scale_factor = float(mtr_canon_paths['size_scaling_factor'])

        # ##################### Sub-vocabulary definitions ############################
        vis_vocab = vocab.create_subset(vis_sp_strs)
        vis_vocab_nums_inds = range(len(num_sp_strs))
        vis_vocab_syms_inds = range(len(num_sp_strs), len(vis_sp_strs))

        pos_vocab = vocab.create_subset(pos_sp_strs)

        item_vocab = vocab.create_subset(num_sp_strs)

        ps_task_vocab = vocab.create_subset(ps_task_sp_strs)
        ps_state_vocab = vocab.create_subset(ps_state_sp_strs)
        ps_dec_vocab = vocab.create_subset(ps_dec_sp_strs)
        ps_cmp_vocab = vocab.create_subset(misc_ps_sp_strs)

        # ################ Enumerated vocabulary definitions ##########################
        # --- Enumerated vocabulary, enumerates all possible combinations of position
        #     and item vectors (for debug purposes)
        enum_vocab = Vocabulary(cfg.sp_dim, rng=cfg.rng)
        for pos in pos_sp_strs:
            for num in num_sp_strs:
                enum_vocab.add('%s*%s' % (pos, num), vocab[pos] * vocab[num])

        pos1_vocab = Vocabulary(cfg.sp_dim, rng=cfg.rng)
        for num in num_sp_strs:
            pos1_vocab.add('%s*%s' % (pos_sp_strs[0], num),
                           vocab[pos_sp_strs[0]] * vocab[num])

        # ############## Semantic pointer lists for signal generation #################
        item_mb_gate_sp_strs = list(num_sp_strs)
        item_mb_gate_sp_inds = strs_to_inds(item_mb_gate_sp_strs, vis_sp_strs)
        item_mb_rst_sp_strs = ['A', 'OPEN']
        item_mb_rst_sp_inds = strs_to_inds(item_mb_rst_sp_strs, vis_sp_strs)

        ave_mb_gate_sp_strs = ['CLOSE']
        ave_mb_gate_sp_inds = strs_to_inds(ave_mb_gate_sp_strs, vis_sp_strs)
        ave_mb_rst_sp_strs = ['A']
        ave_mb_rst_sp_inds = strs_to_inds(ave_mb_rst_sp_strs, vis_sp_strs)

        pos_mb_gate_sp_strs = list(num_sp_strs)
        # pos_mb_gate_sp_strs.extend(['A', 'OPEN', 'QM'])
        pos_mb_gate_sp_inds = strs_to_inds(pos_mb_gate_sp_strs, vis_sp_strs)
        pos_mb_rst_sp_strs = ['A', 'OPEN', 'QM']
        pos_mb_rst_sp_inds = strs_to_inds(pos_mb_rst_sp_strs, vis_sp_strs)
        pos_mb_acc_rst_sp_strs = ['OPEN']
        pos_mb_acc_rst_sp_inds = strs_to_inds(pos_mb_acc_rst_sp_strs, vis_sp_strs)

        # ps_task_mb_gate_sp_strs = list(num_sp_strs)
        # ps_task_mb_gate_sp_strs.extend(['QM'])
        ps_task_mb_gate_sp_strs = ['QM']
        ps_task_mb_gate_sp_inds = strs_to_inds(ps_task_mb_gate_sp_strs, vis_sp_strs)

        ps_task_init_vis_sp_strs = list(num_sp_strs)
        ps_task_init_vis_sp_inds = strs_to_inds(ps_task_init_vis_sp_strs, vis_sp_strs)

        ps_task_init_task_sp_strs = ['X']
        ps_task_init_task_sp_inds = strs_to_inds(ps_task_init_task_sp_strs,
                                                 ps_task_sp_strs)

        ps_task_mb_rst_sp_strs = ['A']
        ps_task_mb_rst_sp_inds = strs_to_inds(ps_task_mb_rst_sp_strs, vis_sp_strs)

        ps_state_mb_gate_sp_strs = ['CLOSE', 'K', 'P']
        ps_state_mb_gate_sp_inds = strs_to_inds(ps_state_mb_gate_sp_strs, vis_sp_strs)

        ps_state_mb_rst_sp_strs = ['A']
        ps_state_mb_rst_sp_inds = strs_to_inds(ps_state_mb_rst_sp_strs, vis_sp_strs)

        ps_dec_mb_gate_sp_strs = ['F', 'R', 'QM']
        ps_dec_mb_gate_sp_inds = strs_to_inds(ps_dec_mb_gate_sp_strs, vis_sp_strs)

        ps_dec_mb_rst_sp_strs = ['A']
        ps_dec_mb_rst_sp_inds = strs_to_inds(ps_dec_mb_rst_sp_strs, vis_sp_strs)

        # Note: sum_vocab_vecs have to be fed through threshold before use.
        dec_out_sr_sp_vecs = vocab.parse('FWD + REV + CNT + DECI').v
        dec_out_copy_draw_sp_vecs = vocab.parse('DECW').v
        dec_out_fr_sp_vecs = vocab.parse('0').v  # TODO: Implement

        dec_pos_gate_dec_sp_vecs = vocab.parse('DECW + DECI + FWD + REV').v
        dec_pos_gate_task_sp_vecs = vocab.parse('DEC').v

        mtr_init_task_sp_vecs = vocab.parse('DEC').v
        mtr_bypass_task_sp_vecs = vocab.parse('CNT').v

        attrs = []
        attrs += [vis_vocab, pos_vocab, enum_vocab]
        attrs += [ps_task_vocab, ps_state_vocab, ps_dec_vocab, ps_cmp_vocab]
        attrs += [mtr_vocab, mtr_disp_vocab, item_vocab, pos1_vocab, vocab]
        attrs += [mtr_sp_scale_factor]


        for attr in
