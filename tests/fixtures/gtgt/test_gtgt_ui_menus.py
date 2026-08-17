# -*- coding: utf-8 -*-
"""Lượt giao diện — gộp menu thuế. Không đụng máy tính chỉ tiêu."""
from odoo.tests import tagged, TransactionCase


@tagged('post_install', '-at_install', 'connecta_vas', 'connecta_vas_gtgt_ui')
class TestGtgtTaxMenuLayout(TransactionCase):

    def test_tax_menu_only_declaration(self):
        tax = self.env.ref('connecta_vas.menu_vas_ops_tax')
        names = tax.child_id.filtered(lambda m: m.active).mapped('name')
        self.assertEqual(set(names), {'Tờ khai 01/GTGT'}, names)
        self.assertFalse(
            self.env.ref(
                'connecta_vas.menu_vas_gtgt_listing',
                raise_if_not_found=False,
            ),
        )
        for xmlid in (
            'menu_vas_tax_deduction_rule_under_tax',
            'menu_vas_input_tax_lines_under_tax',
            'menu_vas_input_tax_lines',
        ):
            self.assertFalse(
                self.env.ref('connecta_vas.%s' % xmlid, raise_if_not_found=False),
                xmlid,
            )

    def test_config_and_catalog_parents(self):
        config = self.env.ref('connecta_vas.menu_vas_config')
        catalog = self.env.ref('connecta_vas.menu_vas_catalog_root')
        self.assertEqual(
            self.env.ref('connecta_vas.menu_vas_gtgt_tax_method').parent_id,
            config,
        )
        for xmlid in (
            'menu_vas_gtgt_form_version',
            'menu_vas_gtgt_reduction_exclusion',
            'menu_vas_gtgt_direct_industry',
            'menu_vas_tax_deduction_rule',
        ):
            self.assertEqual(
                self.env.ref('connecta_vas.%s' % xmlid).parent_id,
                catalog,
                xmlid,
            )

    def test_declaration_list_has_shortcuts(self):
        arch = self.env.ref(
            'connecta_vas.view_vas_gtgt_declaration_list',
        ).arch_db
        self.assertIn('action_open_gtgt_registration', arch)
        self.assertIn('action_open_gtgt_tax_method', arch)

    def test_declaration_form_tabs(self):
        arch = self.env.ref(
            'connecta_vas.view_vas_gtgt_declaration_form',
        ).arch_db
        self.assertIn('name="declaration_face"', arch)
        self.assertIn('name="listing_sale"', arch)
        self.assertIn('name="listing_purchase"', arch)
        self.assertIn('name="input_tax"', arch)
        self.assertIn('invisible="not show_input_tax_tab"', arch)

    def test_input_tax_tab_follows_exempt_flag(self):
        Decl = self.env['vas.gtgt.declaration']
        company = self.env.company
        company.vas_has_exempt_sales = False
        rec = Decl.new({'company_id': company.id})
        self.assertFalse(rec.show_input_tax_tab)
        company.vas_has_exempt_sales = True
        rec2 = Decl.new({'company_id': company.id})
        self.assertTrue(rec2.show_input_tax_tab)

    def test_exclusion_names_no_ocr(self):
        Excl = self.env['vas.gtgt.reduction.exclusion']
        ocr = Excl.search([('name', 'ilike', 'OCR')])
        self.assertFalse(ocr, ocr.mapped('name'))
        und = Excl.search([('name', 'ilike', 'Chưa xác định')])
        self.assertLessEqual(len(und), 5, und.mapped(lambda r: '%s:%s' % (r.code, r.name)))

    def test_ops_hub_tax_keeps_legacy_two(self):
        payload = self.env['vas.ops.group'].get_workflow_payload('tax')
        labels = (
            [p['label'] for p in payload['process']]
            + [d['label'] for d in payload['detached']]
        )
        self.assertIn('Khấu trừ GTGT (L06)', labels)
        self.assertIn('GTGT hàng nhập khẩu', labels)
        self.assertNotIn('Tờ khai 01/GTGT', labels)
