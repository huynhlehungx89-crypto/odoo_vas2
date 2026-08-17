# -*- coding: utf-8 -*-
"""B03 WC: aggregate_by_partner chỉ mã công nợ 10/12; chú thích Δ đúng dấu."""


def migrate(cr, version):
    cr.execute(
        """
        UPDATE vas_report_line
           SET aggregate_by_partner = TRUE,
               basis_note = 'Δ=open_dr−close_dr (tăng PT→âm); tách đối tác; 15581 tr.46–47'
         WHERE form_code = 'B03-DNN'
           AND code = '10'
        """
    )
    cr.execute(
        """
        UPDATE vas_report_line
           SET aggregate_by_partner = FALSE,
               basis_note = 'Δ=open_dr−close_dr SD thuần TK (không tách ĐT); 15581 tr.47'
         WHERE form_code = 'B03-DNN'
           AND code = '11'
        """
    )
    cr.execute(
        """
        UPDATE vas_report_line
           SET aggregate_by_partner = TRUE,
               basis_note = 'Δ=close_cr−open_cr; tách ĐT; gồm 335 trừ lãi vas.loan; 15581 tr.48'
         WHERE form_code = 'B03-DNN'
           AND code = '12'
        """
    )
    cr.execute(
        """
        UPDATE vas_report_line
           SET aggregate_by_partner = FALSE,
               basis_note = 'Δ=open_dr−close_dr SD thuần 242 (không tách ĐT); 15581 tr.48'
         WHERE form_code = 'B03-DNN'
           AND code = '13'
        """
    )
    cr.execute(
        """
        UPDATE vas_report_line
           SET aggregate_by_partner = FALSE,
               basis_note = 'Δ=open_dr−close_dr SD thuần 121 (không tách ĐT); 15581 tr.48'
         WHERE form_code = 'B03-DNN'
           AND code = '14'
        """
    )
