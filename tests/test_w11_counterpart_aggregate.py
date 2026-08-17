# -*- coding: utf-8 -*-
"""Khung phát sinh đối ứng — gom cặp SQL, khớp sổ chi tiết, cảnh báo N×N."""
from odoo.tests import tagged, TransactionCase
from odoo.tools.float_utils import float_compare, float_round

from odoo.addons.connecta_vas.tests.common_vas_query_count import VasQueryCounter


@tagged('post_install', '-at_install', 'connecta_vas', 'connecta_vas_w11')
class TestCounterpartAggregate(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.regime = cls.env.ref('connecta_vas.vas_regime_tt133')
        vnd = cls.env.ref('base.VND')
        cls.company = cls.env['res.company'].create({
            'name': 'W11-CP Thử',
            'currency_id': vnd.id,
            'vas_regime_id': cls.regime.id,
            'vas_start_date': '2094-01-01',
        })
        cls.env.user.company_ids = [(4, cls.company.id)]
        cls.env.user.company_id = cls.company
        cls.fy = cls.env['vas.fiscalyear'].create({
            'name': 'W11-CP-2094',
            'date_from': '2094-01-01',
            'date_to': '2094-12-31',
            'state': 'open',
            'company_id': cls.company.id,
        })
        cls.period = cls.env['vas.period'].create({
            'name': '06/2094',
            'date_start': '2094-06-01',
            'date_end': '2094-06-30',
            'fiscalyear_id': cls.fy.id,
            'state': 'open',
        })
        cls.env['vas.journal']._ensure_journals_for_company(cls.company)
        cls.journal = cls.env['vas.journal'].search([
            ('company_id', '=', cls.company.id), ('code', '=', 'TH'),
        ], limit=1)
        cls.Agg = cls.env['vas.books.aggregate']

    def _acc(self, code):
        return self.env.ref('connecta_vas.vas_account_tt133_%s' % code)

    def _post(self, date, lines, ref='CP', move_kind='manual'):
        move = self.env['vas.move'].create({
            'date': date,
            'journal_id': self.journal.id,
            'regime_id': self.regime.id,
            'company_id': self.company.id,
            'ref': ref,
            'move_kind': move_kind,
            'line_ids': [(0, 0, {
                'account_id': acc.id,
                'name': name,
                'debit': deb,
                'credit': cre,
            }) for acc, name, deb, cre in lines],
        })
        move.action_post()
        return move

    def _pairs(self):
        return self.Agg._books_counterpart_pairs(
            self.company,
            self.period.date_start,
            self.period.date_end,
            hide_reversed=True,
        )

    def _ledger_cp_sum(self, account, counterpart_code, side):
        """Tổng PS trên sổ chi tiết có TK đối ứng = counterpart_code."""
        wiz = self.env['vas.account.ledger.wizard'].create({
            'company_id': self.company.id,
            'account_id': account.id,
            'period_from_id': self.period.id,
            'period_to_id': self.period.id,
            'hide_reversed': True,
        })
        rows, _op, _cl, _pd, _pc = wiz._build_book_rows()
        total = 0.0
        for row in rows:
            if row.get('counterpart_code') != counterpart_code:
                continue
            if side == 'debit':
                total += row.get('debit') or 0.0
            else:
                total += row.get('credit') or 0.0
        return float_round(total, 2)

    def test_01_closing_pair_one_one(self):
        """Chứng từ kết chuyển 1 Nợ 1 Có → cặp thẳng."""
        a632 = self._acc('632')
        a911 = self._acc('911')
        self._post('2094-06-15', [
            (a911, 'KC GV', 25_000_000, 0),
            (a632, 'KC GV', 0, 25_000_000),
        ], ref='KC-1-1', move_kind='closing')
        result = self._pairs()
        amt = self.Agg._books_counterpart_lookup(
            result['pairs'], [a632.id], 'credit', [a911.id], 'debit',
        )
        self.assertEqual(float_compare(amt, 25_000_000, 2), 0)
        amt_rev = self.Agg._books_counterpart_lookup(
            result['pairs'], [a911.id], 'debit', [a632.id], 'credit',
        )
        self.assertEqual(float_compare(amt_rev, 25_000_000, 2), 0)
        self.assertFalse(result['ambiguous_moves'])
        led = self._ledger_cp_sum(a632, '911', 'credit')
        self.assertEqual(float_compare(led, 25_000_000, 2), 0, led)

    def test_02_one_debit_many_credit_proportional(self):
        """1 Nợ nhiều Có — tỷ lệ + khớp sổ chi tiết."""
        a111 = self._acc('111')
        a511 = self._acc('511')
        a131 = self._acc('131')
        self._post('2094-06-16', [
            (a111, 'Thu', 100_000, 0),
            (a511, 'DT1', 0, 60_000),
            (a131, 'CN', 0, 40_000),
        ], ref='1N-mC')
        result = self._pairs()
        p511 = self.Agg._books_counterpart_lookup(
            result['pairs'], [a111.id], 'debit', [a511.id], 'credit',
        )
        p131 = self.Agg._books_counterpart_lookup(
            result['pairs'], [a111.id], 'debit', [a131.id], 'credit',
        )
        self.assertEqual(float_compare(p511, 60_000, 2), 0, p511)
        self.assertEqual(float_compare(p131, 40_000, 2), 0, p131)
        led_511 = self._ledger_cp_sum(a111, '511', 'debit')
        led_131 = self._ledger_cp_sum(a111, '131', 'debit')
        self.assertEqual(float_compare(led_511, 60_000, 2), 0, led_511)
        self.assertEqual(float_compare(led_131, 40_000, 2), 0, led_131)
        # Chiều ngược từ 511: toàn bộ 60k đối ứng 111
        from_511 = self.Agg._books_counterpart_lookup(
            result['pairs'], [a511.id], 'credit', [a111.id], 'debit',
        )
        self.assertEqual(float_compare(from_511, 60_000, 2), 0)

    def test_03_many_many_no_pair_and_warn(self):
        """Nhiều Nợ × nhiều Có — không ghép + có cảnh báo."""
        a111 = self._acc('111')
        a112 = self._acc('112')
        a511 = self._acc('511')
        a515 = self._acc('515')
        move = self._post('2094-06-17', [
            (a111, 'N1', 30_000, 0),
            (a112, 'N2', 70_000, 0),
            (a511, 'C1', 0, 40_000),
            (a515, 'C2', 0, 60_000),
        ], ref='NxN-WARN')
        result = self._pairs()
        self.assertTrue(result['ambiguous_moves'], 'Phải có cảnh báo N×N')
        amb = result['ambiguous_moves']
        self.assertTrue(any(a['move_id'] == move.id for a in amb), amb)
        hit = next(a for a in amb if a['move_id'] == move.id)
        self.assertEqual(hit['n_debit'], 2)
        self.assertEqual(hit['n_credit'], 2)
        self.assertEqual(float_compare(hit['amount'], 100_000, 2), 0)
        # Không có cặp từ chứng từ này
        for src, side_s, opp, side_o in (
            (a111.id, 'debit', a511.id, 'credit'),
            (a111.id, 'debit', a515.id, 'credit'),
            (a112.id, 'debit', a511.id, 'credit'),
            (a112.id, 'debit', a515.id, 'credit'),
        ):
            self.assertEqual(
                result['pairs'].get((src, side_s, opp, side_o), 0.0), 0.0,
            )

    def test_04_query_count_fixed_vs_specs(self):
        """Nhân đôi số chỉ tiêu (spec) — số câu SQL không đổi."""
        a632 = self._acc('632')
        a911 = self._acc('911')
        self._post('2094-06-18', [
            (a911, 'KC', 1_000_000, 0),
            (a632, 'KC', 0, 1_000_000),
        ], move_kind='closing')
        base_specs = [
            (i, [a632.id], 'credit', [a911.id], 'debit')
            for i in range(5)
        ]
        double_specs = [
            (i, [a632.id], 'credit', [a911.id], 'debit')
            for i in range(10)
        ]
        self.env.flush_all()
        with VasQueryCounter(self.env.cr) as qc1:
            self.Agg._books_counterpart_amounts_for_specs(
                self.company, self.period.date_start, self.period.date_end,
                base_specs, hide_reversed=True,
            )
            self.env.flush_all()
        with VasQueryCounter(self.env.cr) as qc2:
            self.Agg._books_counterpart_amounts_for_specs(
                self.company, self.period.date_start, self.period.date_end,
                double_specs, hide_reversed=True,
            )
            self.env.flush_all()
        print('CP_QUERY_COUNT base_specs=%s q=%s double_specs=%s q=%s' % (
            len(base_specs), qc1.count, len(double_specs), qc2.count,
        ))
        self.assertEqual(qc1.count, qc2.count)

    def test_05_reverse_closing_no_double(self):
        """Đảo lô KC rồi KC lại — PS đối ứng không nhân đôi."""
        a632 = self._acc('632')
        a911 = self._acc('911')
        m1 = self._post('2094-06-19', [
            (a911, 'KC1', 8_000_000, 0),
            (a632, 'KC1', 0, 8_000_000),
        ], ref='KC-REV-1', move_kind='closing')
        before = self.Agg._books_counterpart_lookup(
            self._pairs()['pairs'], [a632.id], 'credit', [a911.id], 'debit',
        )
        self.assertEqual(float_compare(before, 8_000_000, 2), 0)
        m1.action_reverse()
        after_rev = self.Agg._books_counterpart_lookup(
            self._pairs()['pairs'], [a632.id], 'credit', [a911.id], 'debit',
        )
        self.assertEqual(float_compare(after_rev, 0.0, 2), 0, after_rev)
        self._post('2094-06-20', [
            (a911, 'KC2', 8_000_000, 0),
            (a632, 'KC2', 0, 8_000_000),
        ], ref='KC-REV-2', move_kind='closing')
        after = self.Agg._books_counterpart_lookup(
            self._pairs()['pairs'], [a632.id], 'credit', [a911.id], 'debit',
        )
        self.assertEqual(float_compare(after, 8_000_000, 2), 0, after)

    def test_06_report_line_fields_and_seed_protect(self):
        """Field khai đối ứng + code_custom; seed B01a vẫn chặn sửa cấu trúc."""
        Line = self.env['vas.report.line']
        self.assertIn('counterpart', dict(Line._fields['turnover_mode'].selection))
        self.assertIn('code_custom', dict(Line._fields['amount_source'].selection))
        seed = self.env.ref('connecta_vas.vas_report_line_b01a_110')
        with self.assertRaises(Exception):
            seed.write({'turnover_mode': 'counterpart'})


@tagged('post_install', '-at_install', 'connecta_vas', 'connecta_vas_w11')
class TestCounterpartVsLedgerW11(TransactionCase):
    """Đối chiếu khung vs sổ chi tiết trên W11-Thử BCTC + đếm hình dạng."""

    def test_01_shape_counts_and_911_632(self):
        self.env['res.company']._vas_w11_ensure_bctc_demo()
        company = self.env['res.company'].search(
            [('name', '=', 'W11-Thử BCTC')], limit=1,
        )
        self.assertTrue(company)
        Agg = self.env['vas.books.aggregate']

        # --- VIỆC 3(a): đếm hình dạng ---
        w11_shapes = Agg._books_move_shape_counts(company)
        print('MOVE_SHAPE W11-Thử BCTC', w11_shapes)

        demo_totals = {
            'one_one': 0, 'one_many': 0, 'many_one': 0, 'many_many': 0, 'total': 0,
        }
        companies = self.env['vas.move'].sudo().read_group(
            [], ['company_id'], ['company_id'], lazy=False,
        )
        for row in companies:
            cid = row['company_id'][0] if row.get('company_id') else False
            if not cid:
                continue
            co = self.env['res.company'].browse(cid)
            sh = Agg._books_move_shape_counts(co)
            for k in demo_totals:
                demo_totals[k] += sh[k]
        print('MOVE_SHAPE demo-1 (all companies)', demo_totals)

        # N×N có thể = 0 trên W11 — vẫn phải có đường cảnh báo (test_03 đã phủ)
        self.assertGreaterEqual(w11_shapes['total'], 1)

        p01 = self.env['vas.period'].search([
            ('fiscalyear_id.company_id', '=', company.id),
            ('date_start', '=', '2026-01-01'),
        ], limit=1)
        p12 = self.env['vas.period'].search([
            ('fiscalyear_id.company_id', '=', company.id),
            ('date_start', '=', '2026-12-01'),
        ], limit=1)
        self.assertTrue(p01 and p12)

        a632 = self.env.ref('connecta_vas.vas_account_tt133_632')
        a911 = self.env.ref('connecta_vas.vas_account_tt133_911')

        result = Agg._books_counterpart_pairs(
            company, p01.date_start, p12.date_end, hide_reversed=True,
        )
        # Có 632 ↔ Nợ 911
        agg_632_911 = Agg._books_counterpart_lookup(
            result['pairs'], [a632.id], 'credit', [a911.id], 'debit',
        )
        # Nợ 911 ↔ Có 632
        agg_911_632 = Agg._books_counterpart_lookup(
            result['pairs'], [a911.id], 'debit', [a632.id], 'credit',
        )

        wiz_632 = self.env['vas.account.ledger.wizard'].create({
            'company_id': company.id,
            'account_id': a632.id,
            'period_from_id': p01.id,
            'period_to_id': p12.id,
            'hide_reversed': True,
        })
        rows_632, *_rest = wiz_632._build_book_rows()
        led_632_911 = float_round(sum(
            (r.get('credit') or 0.0)
            for r in rows_632
            if r.get('counterpart_code') == '911'
        ), 2)

        wiz_911 = self.env['vas.account.ledger.wizard'].create({
            'company_id': company.id,
            'account_id': a911.id,
            'period_from_id': p01.id,
            'period_to_id': p12.id,
            'hide_reversed': True,
        })
        rows_911, *_r2 = wiz_911._build_book_rows()
        led_911_632 = float_round(sum(
            (r.get('debit') or 0.0)
            for r in rows_911
            if r.get('counterpart_code') == '632'
        ), 2)

        print(
            'COMPARE_CP '
            '632_credit_vs_911: agg=%s ledger=%s | '
            '911_debit_vs_632: agg=%s ledger=%s | '
            'ambiguous=%s'
            % (
                agg_632_911, led_632_911,
                agg_911_632, led_911_632,
                len(result['ambiguous_moves']),
            )
        )
        self.assertEqual(
            float_compare(agg_632_911, led_632_911, 2), 0,
            '632↔911 lệch: agg=%s ledger=%s' % (agg_632_911, led_632_911),
        )
        self.assertEqual(
            float_compare(agg_911_632, led_911_632, 2), 0,
            '911↔632 lệch: agg=%s ledger=%s' % (agg_911_632, led_911_632),
        )
        # Năm sau KC: PS Có 632 đối ứng 911 phải > 0
        self.assertGreater(agg_632_911, 0.0)
