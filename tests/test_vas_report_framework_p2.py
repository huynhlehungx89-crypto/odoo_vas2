# -*- coding: utf-8 -*-
"""Pha 2 — rollup cha–con F01 + retrofit sổ chi tiết qua hợp đồng."""
from odoo import fields
from odoo.tests import tagged, TransactionCase
from odoo.tools import float_compare

from odoo.addons.connecta_vas.models.vas_account_ledger import LEDGER_COLUMNS_S12, LEDGER_COLUMNS_S19
from odoo.addons.connecta_vas.models.vas_trial_balance import F01_COLUMNS


@tagged('connecta_vas', 'connecta_vas_report_framework')
class TestVasReportFrameworkP2(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.vnd = cls.env.ref('base.VND')
        if cls.company.currency_id != cls.vnd:
            cls.company.currency_id = cls.vnd

        cls.regime = cls.env['vas.regime'].create({
            'code': 'TT133_FW2',
            'name': 'TT133 Framework P2',
        })
        cls.company.vas_regime_id = cls.regime
        cls.company.vas_start_date = '2096-01-01'

        Account = cls.env['vas.account']

        def mk(code, name, atype='asset', parent=None, reconcile=False):
            pol = {
                'asset': 'debit', 'liability': 'credit', 'equity': 'debit_or_credit',
                'income': 'none', 'expense': 'none', 'other_income': 'none',
                'other_expense': 'none', 'pl': 'none',
            }.get(atype, 'debit_or_credit')
            vals = {
                'code': code,
                'name': name,
                'regime_id': cls.regime.id,
                'account_type': atype,
                'parent_id': parent.id if parent else False,
                'reconcile': reconcile,
            }
            if parent:
                # thừa kế từ cha — không cần khai; để create tự lấy
                pass
            else:
                vals['ending_balance_policy'] = pol
            return Account.create(vals)

        cls.acc_642 = mk('642', 'Chi phi QLDN', 'expense')
        cls.acc_6421 = mk('6421', 'Chi phi nhan vien', 'expense', parent=cls.acc_642)
        cls.acc_6422 = mk('6422', 'Chi phi vat lieu', 'expense', parent=cls.acc_642)
        cls.acc_111 = mk('111', 'Tien mat P2')
        cls.acc_156 = mk('156', 'Hang hoa P2')
        cls.acc_1561 = mk('1561', 'HH vat tu', parent=cls.acc_156)
        cls.acc_1562 = mk('1562', 'HH thanh pham', parent=cls.acc_156)
        cls.acc_411 = mk('411', 'Von P2', 'equity')
        cls.acc_131 = mk('131', 'Phai thu P2', reconcile=True)
        cls.acc_5111 = mk('5111', 'DT P2', 'income')

        cls.sequence = cls.env['ir.sequence'].create({
            'name': 'VAS FW2 Seq',
            'code': 'vas.move.fw2.test',
            'prefix': 'FW2/%(year)s/',
            'padding': 4,
            'company_id': cls.company.id,
        })
        cls.journal = cls.env['vas.journal'].create({
            'code': 'FW2',
            'name': 'FW2 journal',
            'type': 'general',
            'regime_id': cls.regime.id,
            'sequence_id': cls.sequence.id,
            'company_id': cls.company.id,
        })
        cls.fy = cls.env['vas.fiscalyear'].create({
            'name': '2096',
            'date_from': '2096-01-01',
            'date_to': '2096-12-31',
            'state': 'open',
            'company_id': cls.company.id,
        })
        # FY create đã sinh kỳ tháng — lấy sẵn, không create trùng/chồng
        cls.p01 = cls.fy.period_ids.filtered(lambda p: p.date_start.month == 1)[:1]
        cls.p02 = cls.fy.period_ids.filtered(lambda p: p.date_start.month == 2)[:1]
        if not cls.p01 or not cls.p02:
            raise AssertionError('FY 2096 missing Jan/Feb periods')
        cls.partner_a = cls.env['res.partner'].create({
            'name': 'KH FW2 A', 'company_id': cls.company.id, 'customer_rank': 1,
        })

    def _post(self, date, lines, move_kind='manual', **extra):
        move = self.env['vas.move'].create({
            'date': date,
            'journal_id': self.journal.id,
            'regime_id': self.regime.id,
            'move_kind': move_kind,
            'company_id': self.company.id,
            'currency_id': self.vnd.id,
            'ref': extra.pop('ref', 'FW2'),
            'line_ids': [
                fields.Command.create({
                    'account_id': vals['account'].id,
                    'name': 'l',
                    'debit': vals.get('debit', 0.0),
                    'credit': vals.get('credit', 0.0),
                    'partner_id': vals['partner'].id if vals.get('partner') else False,
                })
                for vals in lines
            ],
            **extra,
        })
        move.action_post()
        return move

    def _options_f01(self):
        return {
            'company_id': self.company.id,
            'period_from_id': self.p02.id,
            'period_to_id': self.p02.id,
            'hide_reversed': True,
        }

    def _options_ledger(self, account, partner=None):
        return {
            'company_id': self.company.id,
            'period_from_id': self.p02.id,
            'period_to_id': self.p02.id,
            'account_id': account.id,
            'partner_id': partner.id if partner else False,
            'hide_reversed': True,
        }

    def _seed_rollup(self):
        # Opening trên lá 1561/1562
        self._post('2096-01-05', [
            {'account': self.acc_1561, 'debit': 3_000_000},
            {'account': self.acc_411, 'credit': 3_000_000},
        ], move_kind='opening', ref='SDK1')
        self._post('2096-01-05', [
            {'account': self.acc_1562, 'debit': 2_000_000},
            {'account': self.acc_411, 'credit': 2_000_000},
        ], move_kind='opening', ref='SDK2')
        # PS kỳ 02 trên 6421/6422
        self._post('2096-02-10', [
            {'account': self.acc_6421, 'debit': 400_000},
            {'account': self.acc_111, 'credit': 400_000},
        ], ref='NV')
        self._post('2096-02-15', [
            {'account': self.acc_6422, 'debit': 100_000},
            {'account': self.acc_111, 'credit': 100_000},
        ], ref='VL')
        # Xuất 1561
        self._post('2096-02-20', [
            {'account': self.acc_6421, 'debit': 500_000},
            {'account': self.acc_1561, 'credit': 500_000},
        ], move_kind='cogs', ref='XUAT')

    def test_p2_f01_rollup_parent_equals_children(self):
        """Nghiệm thu 2 — xổ TK cha: tổng cha = tổng lá; grand total chỉ lá."""
        self._seed_rollup()
        data = self.env['vas.trial.balance.wizard'].get_report_data(self._options_f01())
        by_id = {l['id']: l for l in data['lines']}

        parent_156 = by_id[f'acc_{self.acc_156.id}']
        child_1561 = by_id[f'acc_{self.acc_1561.id}']
        child_1562 = by_id[f'acc_{self.acc_1562.id}']
        self.assertTrue(parent_156['unfoldable'])
        self.assertTrue(child_1561['is_leaf'] and child_1562['is_leaf'])
        self.assertFalse(parent_156['is_leaf'])
        self.assertEqual(child_1561['parent_id'], parent_156['id'])
        self.assertEqual(child_1562['parent_id'], parent_156['id'])

        for idx in range(2, 8):  # monetary cols
            self.assertEqual(
                float_compare(
                    parent_156['values'][idx],
                    child_1561['values'][idx] + child_1562['values'][idx],
                    2,
                ),
                0,
                f'156 col {idx}',
            )

        parent_642 = by_id[f'acc_{self.acc_642.id}']
        c1 = by_id[f'acc_{self.acc_6421.id}']
        c2 = by_id[f'acc_{self.acc_6422.id}']
        for idx in range(2, 8):
            self.assertEqual(
                float_compare(
                    parent_642['values'][idx],
                    c1['values'][idx] + c2['values'][idx],
                    2,
                ),
                0,
                f'642 col {idx}',
            )

        # Tổng toàn bảng = Σ lá = wizard.action_compute (không đổi Pha 1)
        wiz = self.env['vas.trial.balance.wizard'].create({
            'company_id': self.company.id,
            'period_from_id': self.p02.id,
            'period_to_id': self.p02.id,
            'hide_reversed': True,
        })
        wiz.action_compute()
        total = next(l for l in data['lines'] if l['is_total'])
        self.assertEqual(total['values'][2], wiz.total_opening_debit)
        self.assertEqual(total['values'][3], wiz.total_opening_credit)
        self.assertEqual(total['values'][4], wiz.total_ps_debit)
        self.assertEqual(total['values'][5], wiz.total_ps_credit)
        self.assertEqual(total['values'][6], wiz.total_closing_debit)
        self.assertEqual(total['values'][7], wiz.total_closing_credit)
        self.assertTrue(data['checks']['is_balanced'])

        # Cộng nhầm cha+con phải lệch — chứng minh chỉ lá
        leaf_ps = sum(
            l['values'][4] for l in data['lines'] if l.get('is_leaf')
        )
        with_parents = leaf_ps + parent_156['values'][4] + parent_642['values'][4]
        self.assertNotEqual(float_compare(with_parents, total['values'][4], 2), 0)

        print(
            f'\n=== P2 F01 rollup ===\n'
            f'  156 cha PSNo={parent_156["values"][4]} '
            f'= 1561({child_1561["values"][4]})+1562({child_1562["values"][4]})\n'
            f'  642 cha PSNo={parent_642["values"][4]} '
            f'= 6421({c1["values"][4]})+6422({c2["values"][4]})\n'
            f'  total PS={total["values"][4]}/{total["values"][5]} balanced={data["checks"]["is_balanced"]}\n'
        )

    def test_p2_ledger_s19_matches_wizard(self):
        """Nghiệm thu 1 — sổ S19 qua hợp đồng = từng số bản wizard cũ."""
        self._post('2096-01-10', [
            {'account': self.acc_1561, 'debit': 5_000_000},
            {'account': self.acc_411, 'credit': 5_000_000},
        ], move_kind='stock', ref='Nhap')
        self._post('2096-02-05', [
            {'account': self.acc_6421, 'debit': 2_000_000},
            {'account': self.acc_1561, 'credit': 2_000_000},
        ], move_kind='cogs', ref='Xuat')
        self._post('2096-02-20', [
            {'account': self.acc_1561, 'debit': 1_000_000},
            {'account': self.acc_411, 'credit': 1_000_000},
        ], move_kind='stock', ref='Nhap2')

        opts = self._options_ledger(self.acc_1561)
        data = self.env['vas.account.ledger.wizard'].get_report_data(opts)
        self.assertEqual(
            [c['name'] for c in data['columns']],
            [c['name'] for c in LEDGER_COLUMNS_S19],
        )
        self.assertEqual(data['meta']['form_code'], 'S19-DNN')

        wiz = self.env['vas.account.ledger.wizard'].create({
            'company_id': self.company.id,
            'account_id': self.acc_1561.id,
            'period_from_id': self.p02.id,
            'period_to_id': self.p02.id,
            'hide_reversed': True,
        })
        wiz.action_compute()
        old_rows = wiz.line_ids.sorted(lambda l: (l.book_sequence, l.sequence, l.id))

        # Bỏ header section; chỉ detail lines
        detail = [l for l in data['lines'] if l.get('parent_id')]
        self.assertEqual(len(detail), len(old_rows))
        for new, old in zip(detail, old_rows):
            vals = new['values']
            self.assertEqual(vals[1], old.move_name or '', old.row_type)
            self.assertEqual(vals[3], old.narration or '', old.row_type)
            self.assertEqual(vals[4], old.counterpart_code or '', old.row_type)
            self.assertEqual(float_compare(vals[5], old.debit, 2), 0, old.row_type)
            self.assertEqual(float_compare(vals[6], old.credit, 2), 0, old.row_type)
            self.assertEqual(float_compare(vals[7], old.balance_debit, 2), 0, old.row_type)
            self.assertEqual(float_compare(vals[8], old.balance_credit, 2), 0, old.row_type)

        opening = next(l for l in detail if 'opening' in l['id'])
        closing = next(l for l in detail if 'closing' in l['id'])
        print(
            f'\n=== P2 ledger S19 ===\n'
            f'  dauNo={opening["values"][7]} cuoiNo={closing["values"][7]} '
            f'lines={len(detail)} form={data["meta"]["form_code"]}\n'
        )

    def test_p2_ledger_s12_discount_col_and_partner(self):
        """S12 — cột thời hạn chiết khấu trống + tách đối tượng."""
        self._post('2096-02-08', [
            {'account': self.acc_131, 'debit': 1_100_000, 'partner': self.partner_a},
            {'account': self.acc_5111, 'credit': 1_000_000},
            {'account': self.acc_411, 'credit': 100_000},
        ], ref='Ban A')

        data = self.env['vas.account.ledger.wizard'].get_report_data(
            self._options_ledger(self.acc_131)
        )
        self.assertEqual(
            [c['name'] for c in data['columns']],
            [c['name'] for c in LEDGER_COLUMNS_S12],
        )
        self.assertEqual(data['meta']['form_code'], 'S12-DNN')
        detail = [l for l in data['lines'] if l.get('parent_id')]
        move_lines = [l for l in detail if l.get('is_leaf')]
        self.assertTrue(move_lines)
        for ml in move_lines:
            # index 4 = discount_deadline — luôn trống
            self.assertEqual(ml['values'][4], '')
        print(
            f'\n=== P2 ledger S12 ===\n'
            f'  form={data["meta"]["form_code"]} detail={len(detail)} '
            f'moves={len(move_lines)} discount_empty=ok\n'
        )

    def test_p2_ledger_parent_unfolds_children(self):
        """Cha 156 xổ ra 1561/1562 — tổng cha = tổng con."""
        self._seed_rollup()
        data = self.env['vas.account.ledger.wizard'].get_report_data(
            self._options_ledger(self.acc_156)
        )
        parent = next(l for l in data['lines'] if l['id'] == f'acc_{self.acc_156.id}')
        self.assertTrue(parent['unfoldable'])
        child_headers = [
            l for l in data['lines']
            if l.get('parent_id') == parent['id'] and l.get('unfoldable')
        ]
        self.assertEqual(len(child_headers), 2)
        # PS Nợ/Có cha = tổng header con (index 5/6 trên S19)
        self.assertEqual(
            float_compare(
                parent['values'][5],
                sum(h['values'][5] for h in child_headers),
                2,
            ),
            0,
        )
        self.assertEqual(
            float_compare(
                parent['values'][6],
                sum(h['values'][6] for h in child_headers),
                2,
            ),
            0,
        )
        print(
            f'\n=== P2 ledger parent unfold ===\n'
            f'  parent PS={parent["values"][5]}/{parent["values"][6]} '
            f'children={len(child_headers)}\n'
        )

    def test_p2_xlsx_contract(self):
        self._seed_rollup()
        f01 = self.env['vas.trial.balance.wizard'].get_report_data(self._options_f01())
        content = self.env['vas.report.engine'].render_xlsx_bytes(f01)
        self.assertTrue(content.startswith(b'PK'))
        self.assertGreater(len(content), 500)

        led = self.env['vas.account.ledger.wizard'].get_report_data(
            self._options_ledger(self.acc_1561)
        )
        content2 = self.env['vas.report.engine'].render_xlsx_bytes(led)
        self.assertTrue(content2.startswith(b'PK'))
        print(f'\n=== P2 xlsx f01={len(content)} ledger={len(content2)} ===\n')
