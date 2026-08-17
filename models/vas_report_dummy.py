# -*- coding: utf-8 -*-
"""Báo cáo thử khung VAS — chỉ dùng trong ca kiểm, không menu, không gieo sẵn."""
from odoo import api, models, _


class VasReportDummyWizard(models.TransientModel):
    _name = 'vas.report.dummy.wizard'
    _description = 'Báo cáo thử khung VAS (chỉ ca kiểm)'

    @api.model
    def get_report_data(self, options):
        """Hợp đồng đủ bốn vùng — mẫu thứ bảy không viết giao diện riêng."""
        company = self.env.company
        options = options or {}
        return {
            'meta': {
                'title': _('BÁO CÁO THỬ KHUNG'),
                'form_code': 'TEST-DUMMY',
                'company_name': company.name or '',
                'period_label': _('Kỳ báo cáo: thử'),
                'currency_id': company.currency_id.id,
                'warning': False,
                'requires_account': False,
                'from_snapshot': False,
            },
            'columns': [
                {
                    'name': 'code', 'label': 'Mã số', 'type': 'string',
                    'align': 'left',
                },
                {
                    'name': 'name', 'label': 'Chỉ tiêu', 'type': 'string',
                    'align': 'left',
                },
                {
                    'name': 'amount', 'label': 'Số tiền', 'type': 'monetary',
                    'align': 'right',
                },
            ],
            'lines': [
                {
                    'id': 'dummy_d1',
                    'label': 'Dòng thử',
                    'level': 0,
                    'values': ['01', 'Dòng thử', 0],
                    'unfoldable': False,
                    'unfolded': False,
                    'parent_id': False,
                    'is_total': False,
                    'is_leaf': True,
                    'is_section': False,
                    'class': '',
                },
                {
                    'id': 'dummy_t1',
                    'label': 'Tổng',
                    'level': 0,
                    'values': ['', 'Tổng', 0],
                    'unfoldable': False,
                    'unfolded': False,
                    'parent_id': False,
                    'is_total': True,
                    'is_leaf': False,
                    'is_section': False,
                    'class': 'o_vas_report_total',
                },
            ],
            'options': options,
            'checks': {'from_dummy': True},
        }

    @api.model
    def action_export_xlsx_options(self, options):
        data = self.get_report_data(options)
        return self.env['vas.report.engine'].action_download_xlsx(
            data, 'VAS_TEST_DUMMY.xlsx',
        )

    @api.model
    def action_export_pdf_options(self, options):
        data = self.get_report_data(options)
        return self.env['vas.report.engine'].action_export_pdf_from_data(
            data, 'VAS_TEST_DUMMY.pdf',
        )
