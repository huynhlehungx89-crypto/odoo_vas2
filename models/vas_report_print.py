# -*- coding: utf-8 -*-
"""Wizard in PDF khung VAS — chỉ chứa hợp đồng meta/columns/lines, không menu."""
import json
import re

from odoo import fields, models

_NOTE_REF_SUFFIX = re.compile(r'\.(total|detail|opening|closing)$', re.IGNORECASE)


class VasReportPrintWizard(models.TransientModel):
    _name = 'vas.report.print.wizard'
    _description = 'In PDF báo cáo VAS (khung dùng chung)'

    data_json = fields.Text(required=True)
    filename = fields.Char(default='VAS.pdf')

    def get_payload(self):
        self.ensure_one()
        try:
            return json.loads(self.data_json or '{}')
        except (TypeError, ValueError):
            return {'meta': {}, 'columns': [], 'lines': []}

    def format_print_cell(self, value, col):
        if value is False or value is None or value == '':
            return ''
        if value == 'N/A':
            return 'N/A'
        col = col or {}
        if (
            col.get('display') == 'note_ref'
            or col.get('name') in ('note_b09', 'code')
        ):
            return _NOTE_REF_SUFFIX.sub('', str(value))
        if col.get('type') == 'monetary':
            try:
                n = float(value)
            except (TypeError, ValueError):
                return str(value)
            abs_txt = '{:,.0f}'.format(abs(n)).replace(',', '.')
            if col.get('negative_paren') and n < 0:
                return '(%s)' % abs_txt
            if n < 0:
                return '-' + abs_txt
            return abs_txt
        return str(value)
