import numpy as np
from warnings import warn

import nengo
from nengo.spa.module import Module
from nengo.utils.network import with_self

from ..vocabs import item_vocab, mtr_vocab, mtr_unk_vocab
from ..vocabs import dec_out_sr_sp_vecs, dec_out_copy_draw_sp_vecs
from ..vocabs import dec_out_fr_sp_vecs
from ..vocabs import dec_pos_gate_dec_sp_vecs, dec_pos_gate_task_sp_vecs
from ..vocabs import pos_mb_rst_sp_inds
from ..vocabs import mtr_sp_scale_factor

from .decoding import Serial_Recall_Network, Free_Recall_Network
from .decoding import Visual_Transform_Network, Output_Classification_Network


class InfoDecoding(Module):
    def __init__(self, cfg, label="Info Dec", seed=None, add_to_container=None):
        super(InfoDecoding, self).__init__(label, seed, add_to_container)
        self.cfg = cfg
        self.init_module()

    @with_self
    def init_module(self):
        bias_node = nengo.Node(output=1)

        # ---------------------- Inputs and outputs ------------------------- #
        self.items_input = nengo.Node(size_in=self.cfg.sp_dim)
        self.pos_input = nengo.Node(size_in=self.cfg.sp_dim)

        # ----------------- Inhibition signal generation -------------------- #
        # Inhibition signal for when TASK != DEC
        self.dec_am_task_inhibit = self.cfg.make_thresh_ens_net()
        nengo.Connection(bias_node, self.dec_am_task_inhibit.input,
                         synapse=None)

        # Generic inhibition signal?
        self.dec_am_inhibit = self.cfg.make_thresh_ens_net(0.1)

        # ---------- Decoding POS mem block gate signal generation ---------- #
        # Decoding POS mem block gate signal generation (from motor system)
        self.pos_mb_gate_bias = self.cfg.make_thresh_ens_net(n_neurons=100)
        self.pos_mb_gate_sig = self.cfg.make_thresh_ens_net(0.3)

        # Bias does ...?
        # Gate signal does ...?

        # Suppress pos_mb gate bias unless task=DEC + dec=FWD|REV|DECI|DECW
        nengo.Connection(bias_node, self.pos_mb_gate_bias.input, transform=-1)

        # -------------------- Serial decoding network ---------------------- #
        serial_decode = Serial_Recall_Network()
        nengo.Connection(self.items_input, serial_decode.items_input,
                         transform=self.cfg.dcconv_item_in_scale, synapse=None)
        nengo.Connection(self.pos_input, serial_decode.pos_input,
                         synapse=None)

        # Inhibitory connections
        nengo.Connection(self.dec_am_task_inhibit.output,
                         serial_decode.inhibit, synapse=0.01)

        # ---------------- Free recall decoding network --------------------- #
        free_recall_decode = Free_Recall_Network()
        nengo.Connection(self.items_input, free_recall_decode.items_input,
                         transform=self.cfg.dec_fr_item_in_scale, synapse=None)
        nengo.Connection(self.pos_input, free_recall_decode.pos_input,
                         synapse=None)

        # Add output of free recall am as a small bias to dec_am
        nengo.Connection(free_recall_decode.output, serial_decode.items_input,
                         transform=self.cfg.dec_fr_to_am_scale)

        # Gating connections
        nengo.Connection(self.dec_am_task_inhibit.output,
                         free_recall_decode.reset)
        nengo.Connection(self.pos_mb_gate_bias.output, free_recall_decode.gate,
                         transform=2, synapse=0.08)
        #  Why is there such a large synapse here?
        nengo.Connection(self.pos_mb_gate_sig.output, free_recall_decode.gate,
                         transform=-2, synapse=0.01)

        # Inhibitory connections
        nengo.Connection(self.dec_am_task_inhibit.output,
                         free_recall_decode.inhibit, synapse=0.01)

        # nengo.Connection(self.pos_mb_gate_sig.output,
        #                  free_recall_decode.inhibit, synapse=0.01)
        # IS THIS STILL NEEDED?
        self.free_recall_decode = free_recall_decode

        # ------------- Visual transform decoding network ------------------- #
        if self.cfg.vis_dim > 0:
            vis_trfm_decode = Visual_Transform_Network()
        else:
            from .decoding.vis_trfm_net import Dummy_Visual_Transform_Network
            vis_trfm_decode = \
                Dummy_Visual_Transform_Network(vectors_in=item_vocab.vectors,
                                               vectors_out=mtr_vocab.vectors)

        # -------- Output classification (know / unknown / stop) system ----- #
        output_classify = Output_Classification_Network()
        nengo.Connection(serial_decode.dec_success,
                         output_classify.sr_utils_y,
                         transform=[[1.0] * serial_decode.dec_am1.n_items],
                         synapse=0.01)
        nengo.Connection(serial_decode.am_utils_diff,
                         output_classify.sr_utils_diff, synapse=0.01)
        nengo.Connection(serial_decode.dec_failure,
                         output_classify.sr_utils_n, synapse=0.03)
        nengo.Connection(free_recall_decode.dec_failure,
                         output_classify.fr_utils_n, synapse=0.03)

        # Output classification inhibitory signals
        # - Inhibit UNK when am's are inhibited.
        # - Inhibit UNK and STOP when pos_gate_sig is HIGH
        #   (i.e. decoding system is doing things)
        nengo.Connection(self.dec_am_inhibit.output,
                         output_classify.output_unk_inhibit, synapse=0.03)
        nengo.Connection(self.pos_mb_gate_sig.output,
                         output_classify.output_unk_inhibit, synapse=0.03)
        nengo.Connection(self.pos_mb_gate_sig.output,
                         output_classify.output_stop_inhibit, synapse=0.03)

        # ----------------------- Output selector --------------------------- #
        # 0: Serial decoder output
        # 1: Copy drawing transform output
        # 2: Free recall decoder output
        # 3: UNK mtr SP output
        # 4: NULL (all zeros) output
        self.select_out = self.cfg.make_selector(5, radius=mtr_sp_scale_factor,
                                            dimensions=self.cfg.mtr_dim,
                                            threshold_sel_in=True)

        # Connections for sel0 - SR
        nengo.Connection(serial_decode.output, self.select_out.input0)
        nengo.Connection(output_classify.output_unk, self.select_out.sel0,
                         transform=-1)
        nengo.Connection(output_classify.output_stop, self.select_out.sel4,
                         transform=-1)

        # Connections for sel1 - Copy Drawing
        nengo.Connection(vis_trfm_decode.output, self.select_out.input1)
        nengo.Connection(output_classify.output_unk, self.select_out.sel1,
                         transform=-1)
        nengo.Connection(output_classify.output_stop, self.select_out.sel4,
                         transform=-1)

        # Connections for sel2 - FR
        nengo.Connection(free_recall_decode.mtr_output, self.select_out.input2)
        nengo.Connection(output_classify.output_unk, self.select_out.sel2,
                         transform=-1)
        nengo.Connection(output_classify.output_stop, self.select_out.sel4,
                         transform=-1)

        # Connections for sel3 - UNK
        nengo.Connection(bias_node, self.select_out.input3,
                         transform=mtr_unk_vocab['UNK'].v[:, None])
        nengo.Connection(output_classify.output_unk, self.select_out.sel3)
        nengo.Connection(output_classify.output_stop, self.select_out.sel4,
                         transform=-1)

        # Connections for sel4 - NULL
        nengo.Connection(output_classify.output_stop, self.select_out.sel4)

        # ############################ DEBUG ##################################
        self.item_dcconv = serial_decode.item_dcconv.output
        self.pos_recall_mb = free_recall_decode.pos_recall_mb.output
        self.pos_acc_input = free_recall_decode.pos_acc_input

        self.select_am = self.select_out.sel0
        self.select_vis = self.select_out.sel1

        self.am_out = nengo.Node(size_in=self.cfg.mtr_dim)
        self.vt_out = nengo.Node(size_in=self.cfg.mtr_dim)
        # nengo.Connection(self.dec_am.output, self.am_out, synapse=None)
        # nengo.Connection(self.vis_transform.output, self.vt_out, synapse=None) ## # noqa
        # nengo.Connection(vis_tfrm_relay.output, self.vt_out, synapse=None)

        self.am_utils = serial_decode.dec_am1.linear_output
        self.am2_utils = serial_decode.dec_am2.linear_output
        self.fr_utils = free_recall_decode.fr_am.output_utilities
        self.util_diff = serial_decode.am_utils_diff

        self.am_th_utils = serial_decode.dec_am1.cleaned_output_utilities
        self.fr_th_utils = free_recall_decode.fr_am.cleaned_output_utilities
        self.am_def_th_utils = serial_decode.dec_am1.output_default_ens
        self.fr_def_th_utils = free_recall_decode.fr_am.output_default_ens # noqa

        self.out_class_sr_y = output_classify.sr_utils_y
        self.out_class_sr_diff = output_classify.sr_utils_diff
        self.out_class_sr_n = output_classify.sr_utils_n

        self.debug_task = nengo.Node(size_in=1)

        self.output_know = output_classify.output_know
        self.output_unk = output_classify.output_unk

        self.item_dcconv_a = serial_decode.item_dcconv.A
        self.item_dcconv_b = serial_decode.item_dcconv.B

        # self.util_diff_neg = util_diff_neg.output
        self.sel_signals = nengo.Node(size_in=5)
        for n in range(5):
            nengo.Connection(getattr(self.select_out, 'sel%d' % n),
                             self.sel_signals[n], synapse=None)

        # ########################## END DEBUG ################################

        # Define network inputs and outputs
        self.items_input = self.items_input
        self.pos_input = self.pos_input
        self.pos_acc_input = free_recall_decode.pos_acc_input
        self.vis_trfm_input = vis_trfm_decode.input

        self.output = self.select_out.output
        self.output_stop = output_classify.output_stop

        # Direct motor (digit) index output to the experimenter system
        self.dec_ind_output = nengo.Node(size_in=len(mtr_vocab.keys) + 1)
        nengo.Connection(serial_decode.dec_am1.cleaned_output_utilities,
                         self.dec_ind_output[:len(mtr_vocab.keys)],
                         synapse=None)
        nengo.Connection(output_classify.output_unk,
                         self.dec_ind_output[len(mtr_vocab.keys)],
                         synapse=None)

    def setup_connections(self, parent_net):
        p_net = parent_net

        # Set up connections from vision module
        if hasattr(parent_net, 'vis'):
            vis_am_utils = p_net.vis.am_utilities
            nengo.Connection(vis_am_utils[pos_mb_rst_sp_inds],
                             self.free_recall_decode.reset,
                             transform=[[self.cfg.mb_gate_scale] *
                                        len(pos_mb_rst_sp_inds)])

            nengo.Connection(p_net.vis.mb_output, self.vis_trfm_input)
        else:
            warn("InfoEncoding Module - Cannot connect from 'vis'")

        # Set up connections from production system module
        if hasattr(p_net, 'ps'):
            # Connections for sel0 - SR
            nengo.Connection(p_net.ps.dec, self.select_out.sel0,
                             transform=[dec_out_sr_sp_vecs * 1.0])

            # Connections for sel1 - Copy Drawing
            nengo.Connection(p_net.ps.dec, self.select_out.sel1,
                             transform=[dec_out_copy_draw_sp_vecs * 1.0])

            # Connections for sel2 - FR
            nengo.Connection(p_net.ps.dec, self.select_out.sel2,
                             transform=[dec_out_fr_sp_vecs * 1.0])

            # Connections for gate signals
            nengo.Connection(p_net.ps.dec, self.pos_mb_gate_bias.input,
                             transform=[dec_pos_gate_dec_sp_vecs * 1.0])
            nengo.Connection(p_net.ps.task, self.pos_mb_gate_bias.input,
                             transform=[dec_pos_gate_task_sp_vecs * 1.0])

            # Connections for inhibitory signals
            nengo.Connection(p_net.ps.task, self.dec_am_task_inhibit.input,
                             transform=[dec_pos_gate_task_sp_vecs * -1.0])

            # ###### DEBUG ########
            nengo.Connection(p_net.ps.dec, self.debug_task,
                             transform=[dec_pos_gate_dec_sp_vecs * 1.0])
        else:
            warn("InfoDecoding Module - Could not connect from 'ps'")

        # Set up connections from encoding module
        if hasattr(p_net, 'enc'):
            nengo.Connection(p_net.enc.pos_output, self.pos_input)
            nengo.Connection(p_net.enc.pos_acc_output, self.pos_acc_input)
        else:
            warn("InfoDecoding Module - Could not connect from 'enc'")

        # Set up connections from transform module
        if hasattr(p_net, 'trfm'):
            nengo.Connection(p_net.trfm.output, self.items_input)
        else:
            warn("InfoDecoding Module - Could not connect from 'trfm'")

        # Set up connections from motor module
        if hasattr(p_net, 'mtr'):
            nengo.Connection(p_net.mtr.ramp_reset_hold,
                             self.pos_mb_gate_sig.input,
                             synapse=0.005, transform=5)
            nengo.Connection(p_net.mtr.ramp_reset_hold,
                             self.pos_mb_gate_sig.input,
                             synapse=0.08, transform=-10)

            nengo.Connection(p_net.mtr.ramp_reset_hold,
                             self.dec_am_inhibit.input,
                             synapse=0.005, transform=5)
            nengo.Connection(p_net.mtr.ramp_reset_hold,
                             self.dec_am_inhibit.input,
                             synapse=0.01, transform=-10)
        else:
            warn("InfoDecoding Module - Could not connect from 'mtr'")
