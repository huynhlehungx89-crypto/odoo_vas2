# -*- coding: utf-8 -*-
"""Company VAS fields + W10/W11 click-demo seed."""
from calendar import monthrange
from datetime import date

from odoo import Command, api, fields, models, _
from odoo.tools.float_utils import float_compare, float_is_zero


W10_DEMO_COMPANY_NAME = 'W10-Thử Kết Chuyển'
W10_DEMO_PARTNER_VAT = 'W10-DEMO-KC-VAT'
W11_BCTC_COMPANY_NAME = 'W11-Thử BCTC'
W11_BCTC_PARTNER_VAT = 'W11-DEMO-BCTC-VAT'
W11_BCTC_SEED_REF = 'W11-BCTC-SEED'
W11_BCTC_FINANCE_REF = 'W11-BCTC-FINANCE'
W11_BCTC_A28_REF = 'W11-BCTC-A28'
# Số cố định phần bổ sung tài chính / khác / thuế (dùng test + báo cáo)
W11_BCTC_LOAN_INTEREST = 1_000_000       # mã 23 — vas.loan 30/360
W11_BCTC_FINANCE_INCOME = 2_000_000      # mã 21 — 515
W11_BCTC_NON_INTEREST_635 = 800_000      # cảnh báo 635 còn lại
W11_BCTC_OTHER_INCOME = 1_500_000        # mã 31 — 711
W11_BCTC_OTHER_EXPENSE = 500_000         # mã 32 — 811
W11_BCTC_CIT_AMOUNT = 2_000_000          # mã 51 — nhập tay trên phiếu KC
# Khoản nhỏ chạm 28 dòng B09 loại A (giữ nguyên nghiệp vụ cũ)
W11_BCTC_A28_DEPOSIT = 2_000_000         # 12811 (con 1281 — C1: không ghi thẳng 1281)
W11_BCTC_A28_ADVANCE = 1_000_000         # 141
W11_BCTC_A28_RECV_INT = 1_000_000        # 1368
W11_BCTC_A28_PAY_INT = 1_000_000         # 3368 ↔ 6422
W11_BCTC_A28_INTANG = 3_000_000          # 2113
W11_BCTC_A28_INTANG_DEP = 500_000        # 2143 ↔ 6422
W11_BCTC_A28_CIP = 2_000_000             # 2412
W11_BCTC_A28_WARRANTY = 1_000_000        # 3521 ↔ 6422
W11_BCTC_A28_REV_5111 = 3_000_000        # 5111 (song song DT trên 511 cha)
# Số dư đầu kỳ tiền (B03 mã 60) — không đụng nghiệp vụ kỳ
W11_BCTC_OPENING_REF = 'W11-BCTC-OPENING'
W11_BCTC_CF_LABEL_REF = 'W11-BCTC-CF-LABEL'
W11_BCTC_PAY_INTEREST_REF = 'W11-BCTC-PAY-INT'
W11_BCTC_PAY_CIT_REF = 'W11-BCTC-PAY-CIT'
W11_BCTC_OPENING_CASH_111 = 30_000_000
W11_BCTC_OPENING_CASH_112 = 20_000_000
W11_BCTC_OPENING_CASH = (
    W11_BCTC_OPENING_CASH_111 + W11_BCTC_OPENING_CASH_112
)
# Số gốc trước A28 (seed+finance) — dùng suy số kỳ vọng sau A28
W11_BCTC_BASE_CASH = 224_200_000
W11_BCTC_BASE_BS = 377_200_000
W11_BCTC_BASE_PNL60 = 16_200_000
W11_BCTC_BASE_REV01 = 80_000_000
W11_BCTC_BASE_ADMIN_6422 = 18_000_000
W11_BCTC_A28_CASH_DELTA = (
    -W11_BCTC_A28_DEPOSIT
    - W11_BCTC_A28_ADVANCE
    - W11_BCTC_A28_RECV_INT
    - W11_BCTC_A28_INTANG
    - W11_BCTC_A28_CIP
    + W11_BCTC_A28_REV_5111
)
W11_BCTC_A28_EXP_6422 = (
    W11_BCTC_A28_PAY_INT
    + W11_BCTC_A28_INTANG_DEP
    + W11_BCTC_A28_WARRANTY
)
W11_BCTC_A28_PNL_DELTA = W11_BCTC_A28_REV_5111 - W11_BCTC_A28_EXP_6422
W11_BCTC_EXPECT_CASH_OPENING = W11_BCTC_OPENING_CASH
# Chi trả lãi + nộp TNDN tiền mặt (B03 mã 15/16) bổ sung sau BASE
W11_BCTC_CF_EXTRA_CASH_OUT = W11_BCTC_LOAN_INTEREST + W11_BCTC_CIT_AMOUNT
W11_BCTC_EXPECT_CASH = (
    W11_BCTC_BASE_CASH + W11_BCTC_A28_CASH_DELTA + W11_BCTC_OPENING_CASH
    - W11_BCTC_CF_EXTRA_CASH_OUT
)
W11_BCTC_EXPECT_BS = W11_BCTC_BASE_BS + W11_BCTC_A28_PNL_DELTA + (
    W11_BCTC_A28_PAY_INT + W11_BCTC_A28_WARRANTY
) + W11_BCTC_OPENING_CASH - W11_BCTC_CF_EXTRA_CASH_OUT
# Tài sản net: +deposit+advance+recv+intang-dep+cip+cash_delta = PNL_DELTA + pay_int + warranty
# = 0.5 + 1 + 1 = 2.5M → BS 379.7M; + opening cash 50M
W11_BCTC_EXPECT_PNL60 = W11_BCTC_BASE_PNL60 + W11_BCTC_A28_PNL_DELTA
W11_BCTC_EXPECT_REV01 = W11_BCTC_BASE_REV01 + W11_BCTC_A28_REV_5111
W11_BCTC_EXPECT_ADMIN = W11_BCTC_BASE_ADMIN_6422 + W11_BCTC_A28_EXP_6422
# Khấu hao kỳ trên W11 (PS Có 2141 seed + 2143 A28) — dùng test B03 mã 03
W11_BCTC_EXPECT_DEP = 10_000_000 + W11_BCTC_A28_INTANG_DEP


class ResCompany(models.Model):
    _inherit = 'res.company'

    vas_regime_id = fields.Many2one(
        'vas.regime',
        string='Chế độ kế toán VAS',
        help='Default VAS accounting regime for this company (TT133 / TT99).',
        ondelete='set null',
    )
    vas_start_date = fields.Date(
        string='Ngày bắt đầu ghi sổ VAS',
        help='Mốc cutoff: đồng bộ chỉ lấy chứng từ có ngày ≥ ngày này; '
             'post vas.move cũng chặn khi chưa khai hoặc ngày < mốc '
             '(trừ số dư đầu kỳ / đảo của nó). Nháp không bị chặn. '
             'Số dư đầu kỳ post đúng ngày này.',
    )
    vas_theo_doi_hang_di_duong = fields.Boolean(
        string='Theo dõi hàng đi đường (TK 151)',
        default=False,
        help='Bật: hóa đơn mua khi chưa nhập kho → Nợ 151 / Có 331; '
             'khi phiếu nhập IN (Vendor→Input) done → Nợ 156 / Có 151. '
             'Tắt (mặc định): 156 chỉ ghi lúc nhận hàng (R06).',
    )
    vas_boc_tach_khau_hao_htk = fields.Boolean(
        string='Bóc tách được số khấu hao nằm trong hàng tồn kho',
        default=False,
        help='TT133 cho doanh nghiệp tự xác định thuộc trường hợp nào; '
             'đây là chính sách kế toán của doanh nghiệp, phải thuyết minh '
             'trong B09. Mặc định: Không. Khi Có: nhập số KH nằm trong HTK '
             'cuối kỳ ở ô bên dưới (mã 03 và 11 dùng ở chặng sau).',
    )
    vas_khau_hao_trong_htk = fields.Float(
        string='Số khấu hao nằm trong HTK cuối kỳ',
        digits=(16, 2),
        default=0.0,
        help='Chỉ dùng khi bật «Bóc tách được số khấu hao nằm trong hàng tồn kho». '
             'Chặng B03-2 dùng số này cho mã 03 và mã 11.',
    )
    vas_has_exempt_sales = fields.Boolean(
        string='Có bán hàng không chịu thuế GTGT',
        default=False,
        help='Tắt (mặc định): mọi thuế đầu vào vào nhóm dùng riêng chịu thuế, '
             'ẩn cột mục đích trên màn phân loại. Bật: phân loại mục đích + '
             'phân bổ dùng chung theo tỷ lệ doanh thu.',
    )
    vas_pos_cash_account_id = fields.Many2one(
        'vas.account',
        string='TK quỹ nộp tiền quầy',
        ondelete='set null',
        help='Bên Nợ kết ca tiền mặt và vế đối ứng rút/bỏ tiền giữa ca. '
             'Trống = 1111 (cờ TK mặc định, chặn khóa kỳ). '
             'Đổi khai báo khi bật két quầy — không cắm cứng trong adapter.',
    )
    vas_scrap_account_id = fields.Many2one(
        'vas.account',
        string='TK đối ứng hủy hàng',
        ondelete='set null',
        help='Bên Nợ phiếu hủy hàng (stock.scrap). Trống = 811 + cờ mặc định, '
             'chặn khóa kỳ. Không tự chọn 632/154/138.',
    )

    def _vas_gtgt_taxable_revenue_ratio(self, on_date):
        """Tỷ lệ DT chịu thuế / tổng DT bán ra trong kỳ chứa on_date.

        Luật 305.pdf Điều 14 khoản 1 điểm b (tr. 121).
        """
        self.ensure_one()
        on_date = fields.Date.to_date(on_date)
        period = self.env['vas.period'].search([
            ('fiscalyear_id.company_id', '=', self.id),
            ('date_start', '<=', on_date),
            ('date_end', '>=', on_date),
        ], limit=1)
        # Tổng DT bán ra: mọi có 511%; tử số chỉ DT chịu thuế (không gồm không chịu / miễn).
        domain_base = [
            ('move_id.company_id', '=', self.id),
            ('move_id.state', '=', 'posted'),
            ('credit', '>', 0),
            ('account_id.code', '=like', '511%'),
        ]
        if period:
            domain_base.append(('period_id', '=', period.id))
        else:
            domain_base += [
                ('date', '>=', on_date.replace(day=1)),
                ('date', '<=', on_date),
            ]
        lines = self.env['vas.move.line'].search(domain_base)
        taxable = 0.0
        total = 0.0
        for line in lines:
            amt = line.credit
            total += amt
            tax = line.tax_id
            if not tax:
                continue
            tag = tax.declaration_value_tag or ''
            code = tax.code or ''
            if tag == '26' or code in ('GTGT_EXEMPT', 'GTGT_NON_TAXABLE'):
                continue
            if tag in ('29', '30', '32', '32a') or code in (
                'GTGT_0', 'GTGT_5', 'GTGT_8', 'GTGT_10',
            ):
                taxable += amt
            elif tax.rate and float_compare(tax.rate, 0.0, 2) > 0:
                taxable += amt
        if float_is_zero(total, precision_digits=2):
            ratio = 1.0
        else:
            ratio = taxable / total
        return {
            'ratio': ratio,
            'numerator': taxable,
            'denominator': total,
            'period': period,
        }

    def vas_gtgt_declaration_block_reason(self, period=None):
        """Chặn lập tờ khai khi còn dòng CHƯA XÁC ĐỊNH (cấu hình bật)."""
        self.ensure_one()
        if not self.vas_has_exempt_sales:
            return False
        domain = [
            ('move_id.company_id', '=', self.id),
            ('move_id.state', '=', 'posted'),
            ('tax_id', '!=', False),
            ('debit', '>', 0),
            ('account_id.code', '=like', '1331%'),
            ('use_purpose', '=', 'unset'),
        ]
        if period:
            domain.append(('period_id', '=', period.id))
        count = self.env['vas.move.line'].search_count(domain)
        if count:
            return _(
                'Còn %(n)s dòng thuế đầu vào CHƯA XÁC ĐỊNH mục đích sử dụng — '
                'không được lập tờ khai GTGT.',
                n=count,
            )
        return False

    @api.model
    def _vas_w10_ensure_click_demo(self):
        """Dựng công ty riêng + số dư mẫu để bấm thử W10. Idempotent."""
        Company = self.env['res.company']
        company = Company.search([('name', '=', W10_DEMO_COMPANY_NAME)], limit=1)
        if company:
            marker = self.env['vas.move'].search([
                ('company_id', '=', company.id),
                ('ref', '=', 'W10-DEMO-SEED'),
            ], limit=1)
            if marker:
                return True

        regime = self.env.ref('connecta_vas.vas_regime_tt133')
        vnd = self.env.ref('base.VND')
        usd = self.env.ref('base.USD')
        usd.active = True

        if not company:
            partner = self.env['res.partner'].create({
                'name': W10_DEMO_COMPANY_NAME,
                'company_type': 'company',
                'vat': W10_DEMO_PARTNER_VAT,
                'is_company': True,
            })
            company = Company.create({
                'name': W10_DEMO_COMPANY_NAME,
                'partner_id': partner.id,
                'currency_id': vnd.id,
                'vas_regime_id': regime.id,
                'vas_start_date': '2026-01-01',
                'fiscalyear_last_day': 31,
                'fiscalyear_last_month': '12',
            })
        else:
            company.write({
                'vas_regime_id': regime.id,
                'vas_start_date': company.vas_start_date or '2026-01-01',
                'currency_id': vnd.id,
            })

        self.env['vas.journal']._ensure_journals_for_company(company)
        journal = self.env['vas.journal'].search([
            ('company_id', '=', company.id), ('code', '=', 'TH'),
        ], limit=1)
        journal_kc = self.env['vas.journal'].search([
            ('company_id', '=', company.id), ('code', '=', 'KC'),
        ], limit=1)

        fy = self.env['vas.fiscalyear'].search([
            ('company_id', '=', company.id),
            ('date_from', '=', '2026-01-01'),
        ], limit=1)
        if not fy:
            fy = self.env['vas.fiscalyear'].create({
                'name': 'Năm 2026 — W10 demo',
                'date_from': '2026-01-01',
                'date_to': '2026-12-31',
                'state': 'open',
                'company_id': company.id,
            })
        for month, start, end in (
            (6, '2026-06-01', '2026-06-30'),
            (12, '2026-12-01', '2026-12-31'),
        ):
            period = self.env['vas.period'].search([
                ('fiscalyear_id', '=', fy.id),
                ('date_start', '=', start),
            ], limit=1)
            if not period:
                self.env['vas.period'].create({
                    'name': '%02d/2026' % month,
                    'date_start': start,
                    'date_end': end,
                    'fiscalyear_id': fy.id,
                    'state': 'open',
                })

        def acc(code):
            return self.env.ref('connecta_vas.vas_account_tt133_%s' % code)

        def post_pair(day, debit, credit, amount, name):
            move = self.env['vas.move'].create({
                'date': day,
                'journal_id': journal.id,
                'regime_id': regime.id,
                'move_kind': 'manual',
                'company_id': company.id,
                'ref': 'W10-DEMO-SEED',
                'narration': name,
                'line_ids': [
                    (0, 0, {
                        'account_id': debit.id, 'name': name,
                        'debit': amount, 'credit': 0.0,
                    }),
                    (0, 0, {
                        'account_id': credit.id, 'name': name,
                        'debit': 0.0, 'credit': amount,
                    }),
                ],
            })
            move.action_post()
            return move

        post_pair('2026-06-10', acc('111'), acc('511'), 50_000_000, 'DT BH')
        # Lá 5111 — giữ nguyên dòng cha 511 ở trên để bấm thử cặp rule cha + lá.
        post_pair('2026-06-10', acc('111'), acc('5111'), 8_000_000, 'DT HH 5111')
        post_pair('2026-06-20', acc('111'), acc('5111'), 4_000_000, 'DT HH 5111 thêm')
        post_pair('2026-06-11', acc('632'), acc('156'), 20_000_000, 'Giá vốn')
        post_pair('2026-06-12', acc('6421'), acc('111'), 3_000_000, 'CP bán hàng')
        post_pair('2026-06-13', acc('6422'), acc('111'), 5_000_000, 'CP QLDN')
        post_pair('2026-06-14', acc('111'), acc('515'), 1_500_000, 'DT tài chính')
        post_pair('2026-06-15', acc('811'), acc('111'), 800_000, 'CP khác')
        post_pair('2026-06-16', acc('511'), acc('111'), 2_000_000, 'Giảm trừ DT Nợ 511')

        post_pair('2026-06-17', acc('1331'), acc('331'), 4_000_000, 'GTGT đầu vào 1331')
        post_pair('2026-06-18', acc('1332'), acc('331'), 1_000_000, 'GTGT đầu vào 1332')
        post_pair('2026-06-19', acc('131'), acc('33311'), 8_000_000, 'GTGT đầu ra 33311')

        post_pair('2026-12-05', acc('111'), acc('511'), 30_000_000, 'DT cuối năm')
        post_pair('2026-12-06', acc('632'), acc('156'), 10_000_000, 'GV cuối năm')

        Rate = self.env['res.currency.rate']
        for day, vnd_per_usd in (('2026-06-01', 24_000.0), ('2026-06-30', 25_000.0)):
            rate_val = 1.0 / vnd_per_usd
            existing = Rate.search([
                ('currency_id', '=', usd.id),
                ('name', '=', day),
                ('company_id', 'in', (False, company.id)),
            ], limit=1)
            if existing:
                existing.write({'rate': rate_val, 'company_id': company.id})
            else:
                Rate.create({
                    'currency_id': usd.id,
                    'name': day,
                    'rate': rate_val,
                    'company_id': company.id,
                })
        partner_fx = self.env['res.partner'].create({
            'name': 'W10 Demo FX Customer',
            'company_id': company.id,
        })
        fx_move = self.env['vas.move'].create({
            'date': '2026-06-10',
            'journal_id': journal.id,
            'regime_id': regime.id,
            'move_kind': 'manual',
            'company_id': company.id,
            'ref': 'W10-DEMO-SEED',
            'narration': 'Tiền gửi USD',
            'line_ids': [
                (0, 0, {
                    'account_id': acc('1122').id,
                    'partner_id': partner_fx.id,
                    'name': 'USD bank',
                    'debit': 24_000_000.0,
                    'credit': 0.0,
                    'amount_currency': 1_000.0,
                    'currency_id': usd.id,
                }),
                (0, 0, {
                    'account_id': acc('511').id,
                    'name': 'USD bank đối ứng',
                    'debit': 0.0,
                    'credit': 24_000_000.0,
                }),
            ],
        })
        fx_move.action_post()

        asset = self.env['vas.asset'].create({
            'code': 'W10-DEMO-242',
            'name': 'Chi phí trả trước demo W10',
            'company_id': company.id,
            'regime_id': regime.id,
            'asset_type': 'prepaid',
            'asset_kind': 'prepaid_service',
            'original_value': 1_200_000,
            'date_start': date(2026, 6, 1),
            'method': 'straight_line',
            'duration_months': 2,
            'prorata': False,
            'account_gross_id': acc('242').id,
            'account_accum_id': acc('242').id,
            'account_expense_id': acc('6422').id,
            'journal_id': journal_kc.id or journal.id,
            'source_mode': 'manual',
        })
        asset.action_confirm()
        return True

    @api.model
    def _vas_w11_ensure_bctc_demo(self):
        """Công ty thử BCTC cân đối 2026 — không đụng W10-Thử Kết Chuyển. Idempotent."""
        Company = self.env['res.company']
        company = Company.search([('name', '=', W11_BCTC_COMPANY_NAME)], limit=1)
        if company:
            marker = self.env['vas.move'].search([
                ('company_id', '=', company.id),
                ('ref', '=', W11_BCTC_SEED_REF),
            ], limit=1)
            if marker:
                self._vas_w11_ensure_bctc_demo_finance(company)
                self._vas_w11_ensure_bctc_demo_a28(company)
                self._vas_w11_ensure_bctc_demo_opening(company)
                return self._vas_w11_ensure_bctc_demo_cashflow_labels(company)

        regime = self.env.ref('connecta_vas.vas_regime_tt133')
        vnd = self.env.ref('base.VND')

        if not company:
            partner = self.env['res.partner'].create({
                'name': W11_BCTC_COMPANY_NAME,
                'company_type': 'company',
                'vat': W11_BCTC_PARTNER_VAT,
                'is_company': True,
            })
            company = Company.create({
                'name': W11_BCTC_COMPANY_NAME,
                'partner_id': partner.id,
                'currency_id': vnd.id,
                'vas_regime_id': regime.id,
                'vas_start_date': '2026-01-01',
                'fiscalyear_last_day': 31,
                'fiscalyear_last_month': '12',
            })
        else:
            company.write({
                'vas_regime_id': regime.id,
                'vas_start_date': company.vas_start_date or '2026-01-01',
                'currency_id': vnd.id,
            })

        self.env['vas.journal']._ensure_journals_for_company(company)
        journal = self.env['vas.journal'].search([
            ('company_id', '=', company.id), ('code', '=', 'TH'),
        ], limit=1)

        fy = self.env['vas.fiscalyear'].search([
            ('company_id', '=', company.id),
            ('date_from', '=', '2026-01-01'),
        ], limit=1)
        if not fy:
            fy = self.env['vas.fiscalyear'].create({
                'name': 'Năm 2026 — W11 BCTC',
                'date_from': '2026-01-01',
                'date_to': '2026-12-31',
                'state': 'open',
                'company_id': company.id,
            })
        for month in range(1, 13):
            start = '2026-%02d-01' % month
            if month == 12:
                end = '2026-12-31'
            else:
                end = '2026-%02d-%02d' % (month, monthrange(2026, month)[1])
            period = self.env['vas.period'].search([
                ('fiscalyear_id', '=', fy.id),
                ('date_start', '=', start),
            ], limit=1)
            if not period:
                self.env['vas.period'].create({
                    'name': '%02d/2026' % month,
                    'date_start': start,
                    'date_end': end,
                    'fiscalyear_id': fy.id,
                    'state': 'open',
                })

        def acc(code):
            return self.env.ref('connecta_vas.vas_account_tt133_%s' % code)

        Partner = self.env['res.partner']

        def ensure_partner(name, vat):
            p = Partner.search([
                ('name', '=', name),
                ('company_id', 'in', (False, company.id)),
            ], limit=1)
            if p:
                if not p.company_id:
                    p.company_id = company.id
                return p
            return Partner.create({
                'name': name,
                'company_id': company.id,
                'vat': vat,
                'is_company': True,
            })

        cust_a = ensure_partner('W11 KH A (nợ)', 'W11-CUST-A')
        cust_b = ensure_partner('W11 KH B (trả trước)', 'W11-CUST-B')
        vend_a = ensure_partner('W11 NCC A (nợ)', 'W11-VEND-A')
        vend_b = ensure_partner('W11 NCC B (trả trước)', 'W11-VEND-B')

        def post_lines(day, lines, name):
            """lines: [(account, debit, credit, partner_or_False), ...]"""
            move = self.env['vas.move'].create({
                'date': day,
                'journal_id': journal.id,
                'regime_id': regime.id,
                'move_kind': 'manual',
                'company_id': company.id,
                'ref': W11_BCTC_SEED_REF,
                'narration': name,
                'line_ids': [
                    (0, 0, {
                        'account_id': a.id,
                        'name': name,
                        'debit': deb,
                        'credit': cre,
                        'partner_id': (p.id if p else False),
                    }) for a, deb, cre, p in lines
                ],
            })
            move.action_post()
            return move

        # 1) Góp vốn bằng tiền
        post_lines('2026-01-05', [
            (acc('111'), 200_000_000, 0, False),
            (acc('4111'), 0, 200_000_000, False),
        ], 'Góp vốn')

        # 2) Mua hàng nhập kho — còn nợ NCC A
        post_lines('2026-02-10', [
            (acc('156'), 50_000_000, 0, vend_a),
            (acc('331'), 0, 50_000_000, vend_a),
        ], 'Mua HH NCC A')
        post_lines('2026-02-20', [
            (acc('331'), 20_000_000, 0, vend_a),
            (acc('111'), 0, 20_000_000, False),
        ], 'Trả một phần NCC A')

        # 3) Trả trước NCC B (331 dư Nợ theo đối tác)
        post_lines('2026-03-01', [
            (acc('331'), 10_000_000, 0, vend_b),
            (acc('111'), 0, 10_000_000, False),
        ], 'Trả trước NCC B')

        # 4) GTGT đầu vào
        post_lines('2026-02-11', [
            (acc('1331'), 5_000_000, 0, vend_a),
            (acc('331'), 0, 5_000_000, vend_a),
        ], 'GTGT đầu vào')

        # 5) Bán hàng — KH A còn nợ; GTGT đầu ra
        post_lines('2026-04-15', [
            (acc('131'), 88_000_000, 0, cust_a),
            (acc('511'), 0, 80_000_000, False),
            (acc('33311'), 0, 8_000_000, False),
        ], 'Bán hàng KH A')
        post_lines('2026-04-16', [
            (acc('632'), 40_000_000, 0, False),
            (acc('156'), 0, 40_000_000, False),
        ], 'Giá vốn')
        post_lines('2026-05-10', [
            (acc('111'), 50_000_000, 0, False),
            (acc('131'), 0, 50_000_000, cust_a),
        ], 'Thu một phần KH A')

        # 6) KH B trả trước (131 dư Có theo đối tác)
        post_lines('2026-06-01', [
            (acc('111'), 15_000_000, 0, False),
            (acc('131'), 0, 15_000_000, cust_b),
        ], 'KH B trả trước')

        # 7) Chi phí bán hàng / QLDN
        post_lines('2026-07-15', [
            (acc('6421'), 5_000_000, 0, False),
            (acc('111'), 0, 5_000_000, False),
        ], 'CP bán hàng')
        post_lines('2026-07-20', [
            (acc('6422'), 8_000_000, 0, False),
            (acc('111'), 0, 8_000_000, False),
        ], 'CP QLDN')

        # 8) Mua TSCĐ + khấu hao
        post_lines('2026-03-15', [
            (acc('2111'), 100_000_000, 0, False),
            (acc('111'), 0, 100_000_000, False),
        ], 'Mua TSCĐ')
        post_lines('2026-12-31', [
            (acc('6422'), 10_000_000, 0, False),
            (acc('2141'), 0, 10_000_000, False),
        ], 'Khấu hao TSCĐ')

        # 9) Kết chuyển cuối năm đầy đủ → 4212; lớp 5–9 về 0
        entry = self.env['vas.closing.entry'].create({
            'company_id': company.id,
            'date_from': '2026-01-01',
            'date_to': '2026-12-31',
            'run_kqkd': True,
            'run_year_start': False,
            'run_fx': False,
            'run_vat': False,
            'run_prepaid': False,
            'run_manual': False,
            'run_cit': False,
            'note': 'W11 BCTC demo year-end close',
        })
        entry.action_fetch_data()
        entry.action_post()
        # Bổ sung vay / TC / khác / thuế + KC lại (idempotent riêng)
        self._vas_w11_ensure_bctc_demo_finance(company)
        self._vas_w11_ensure_bctc_demo_a28(company)
        self._vas_w11_ensure_bctc_demo_opening(company)
        return self._vas_w11_ensure_bctc_demo_cashflow_labels(company)

    @api.model
    def _vas_w11_ensure_bctc_demo_opening(self, company=None):
        """Số dư đầu kỳ 111/112 + đối ứng 4111 — kiểm chứng B03 mã 60. Idempotent."""
        Company = self.env['res.company']
        if company is None:
            company = Company.search([('name', '=', W11_BCTC_COMPANY_NAME)], limit=1)
        if not company:
            return False
        existing = self.env['vas.move'].search([
            ('company_id', '=', company.id),
            ('ref', '=', W11_BCTC_OPENING_REF),
            ('is_reversal', '=', False),
            ('state', 'not in', ('reversed', 'cancelled')),
        ], limit=1)
        if existing:
            return True

        regime = company.vas_regime_id
        journal = self.env['vas.journal'].search([
            ('company_id', '=', company.id), ('code', '=', 'TH'),
        ], limit=1)
        date_open = company.vas_start_date or fields.Date.to_date('2026-01-01')

        def acc(code):
            return self.env.ref('connecta_vas.vas_account_tt133_%s' % code)

        self.env['vas.move'].create({
            'date': date_open,
            'journal_id': journal.id,
            'regime_id': regime.id,
            'company_id': company.id,
            'ref': W11_BCTC_OPENING_REF,
            'move_kind': 'opening',
            'name': 'W11 số dư đầu kỳ tiền',
            'line_ids': [
                (0, 0, {
                    'account_id': acc('111').id,
                    'name': 'TM đầu kỳ',
                    'debit': W11_BCTC_OPENING_CASH_111,
                    'credit': 0,
                }),
                (0, 0, {
                    'account_id': acc('112').id,
                    'name': 'TGNH đầu kỳ',
                    'debit': W11_BCTC_OPENING_CASH_112,
                    'credit': 0,
                }),
                (0, 0, {
                    'account_id': acc('4111').id,
                    'name': 'Vốn CSH đối ứng đầu kỳ',
                    'debit': 0,
                    'credit': W11_BCTC_OPENING_CASH,
                }),
            ],
        }).action_post()
        return True

    @api.model
    def _vas_w11_ensure_bctc_demo_a28(self, company=None):
        """Khoản nhỏ chạm các dòng B09 loại A còn 0 — idempotent theo ref A28."""
        Company = self.env['res.company']
        if company is None:
            company = Company.search([('name', '=', W11_BCTC_COMPANY_NAME)], limit=1)
        if not company:
            return False
        existing = self.env['vas.move'].search([
            ('company_id', '=', company.id),
            ('ref', '=', W11_BCTC_A28_REF),
            ('is_reversal', '=', False),
            ('state', 'not in', ('reversed', 'cancelled')),
        ])
        posted_close = self.env['vas.closing.entry'].search([
            ('company_id', '=', company.id),
            ('date_from', '=', '2026-01-01'),
            ('date_to', '=', '2026-12-31'),
            ('state', '=', 'posted'),
            ('note', 'ilike', '%finance/CIT%'),
        ], limit=1)
        a1281 = self.env.ref('connecta_vas.vas_account_tt133_1281')
        # Bản cũ ghi thẳng 1281 → lệch B01a 200/500 (C1) — đảo để ghi lại lên 12811
        bad_1281 = existing.mapped('line_ids').filtered(
            lambda l: l.account_id == a1281,
        )
        if existing and posted_close and not bad_1281:
            return True

        # Đảo KC năm để ghi thêm rồi KC lại (giữ nguyên chứng từ nghiệp vụ cũ)
        old_entries = self.env['vas.closing.entry'].search([
            ('company_id', '=', company.id),
            ('date_from', '=', '2026-01-01'),
            ('date_to', '=', '2026-12-31'),
            ('state', '=', 'posted'),
        ])
        for entry in old_entries:
            entry.action_reverse_entry()

        if bad_1281:
            for move in existing:
                if move.state == 'posted':
                    move.action_reverse()
            existing = self.env['vas.move']

        if not existing:
            regime = company.vas_regime_id
            journal = self.env['vas.journal'].search([
                ('company_id', '=', company.id), ('code', '=', 'TH'),
            ], limit=1)

            def acc(code):
                return self.env.ref('connecta_vas.vas_account_tt133_%s' % code)

            # C1: ghi tiểu khoản con 12811 (B01a 122); V.2b.deposit roll-up từ 1281
            deposit_acc = acc('12811')

            unit = self.env['res.partner'].search([
                ('name', '=', 'W11 Đơn vị nội bộ'),
                ('company_id', 'in', (False, company.id)),
            ], limit=1)
            if not unit:
                unit = self.env['res.partner'].create({
                    'name': 'W11 Đơn vị nội bộ',
                    'company_id': company.id,
                    'is_company': True,
                })
            emp = self.env['res.partner'].search([
                ('name', '=', 'W11 NV tạm ứng'),
                ('company_id', 'in', (False, company.id)),
            ], limit=1)
            if not emp:
                emp = self.env['res.partner'].create({
                    'name': 'W11 NV tạm ứng',
                    'company_id': company.id,
                    'is_company': False,
                })

            def post_lines(date_str, lines, name):
                move = self.env['vas.move'].create({
                    'date': date_str,
                    'journal_id': journal.id,
                    'regime_id': regime.id,
                    'company_id': company.id,
                    'ref': W11_BCTC_A28_REF,
                    'move_kind': 'manual',
                    'narration': name,
                    'line_ids': [
                        (0, 0, {
                            'account_id': a.id,
                            'name': name,
                            'debit': deb,
                            'credit': cre,
                            'partner_id': p.id if p else False,
                        }) for a, deb, cre, p in lines
                    ],
                })
                move.action_post()
                return move

            post_lines('2026-03-20', [
                (deposit_acc, W11_BCTC_A28_DEPOSIT, 0, False),
                (acc('111'), 0, W11_BCTC_A28_DEPOSIT, False),
            ], 'A28 TG có kỳ hạn 12811')
            post_lines('2026-04-05', [
                (acc('141'), W11_BCTC_A28_ADVANCE, 0, emp),
                (acc('111'), 0, W11_BCTC_A28_ADVANCE, False),
            ], 'A28 tạm ứng NV 141')
            post_lines('2026-04-12', [
                (acc('1368'), W11_BCTC_A28_RECV_INT, 0, unit),
                (acc('111'), 0, W11_BCTC_A28_RECV_INT, False),
            ], 'A28 phải thu nội bộ 1368')
            post_lines('2026-05-08', [
                (acc('6422'), W11_BCTC_A28_PAY_INT, 0, False),
                (acc('3368'), 0, W11_BCTC_A28_PAY_INT, unit),
            ], 'A28 phải trả nội bộ 3368')
            post_lines('2026-05-15', [
                (acc('2113'), W11_BCTC_A28_INTANG, 0, False),
                (acc('111'), 0, W11_BCTC_A28_INTANG, False),
            ], 'A28 mua TSCĐ VH 2113')
            post_lines('2026-12-31', [
                (acc('6422'), W11_BCTC_A28_INTANG_DEP, 0, False),
                (acc('2143'), 0, W11_BCTC_A28_INTANG_DEP, False),
            ], 'A28 KH TSCĐ VH 2143')
            post_lines('2026-06-18', [
                (acc('2412'), W11_BCTC_A28_CIP, 0, False),
                (acc('111'), 0, W11_BCTC_A28_CIP, False),
            ], 'A28 XDCB dở dang 2412')
            post_lines('2026-07-22', [
                (acc('6422'), W11_BCTC_A28_WARRANTY, 0, False),
                (acc('3521'), 0, W11_BCTC_A28_WARRANTY, False),
            ], 'A28 dự phòng bảo hành 3521')
            post_lines('2026-08-25', [
                (acc('111'), W11_BCTC_A28_REV_5111, 0, False),
                (acc('5111'), 0, W11_BCTC_A28_REV_5111, False),
            ], 'A28 DT HH trên 5111')

        entry = self.env['vas.closing.entry'].create({
            'company_id': company.id,
            'date_from': '2026-01-01',
            'date_to': '2026-12-31',
            'run_kqkd': True,
            'run_year_start': False,
            'run_fx': False,
            'run_vat': False,
            'run_prepaid': False,
            'run_manual': False,
            'run_cit': False,
            'note': 'W11 BCTC demo year-end close + finance/CIT + A28',
        })
        entry.action_fetch_data()
        entry.action_post()
        return True

    @api.model
    def _vas_w11_ensure_bctc_demo_finance(self, company=None):
        """Bổ sung nghiệp vụ tài chính + khác + thuế TNDN trên W11-Thử BCTC.

        Idempotent: đã có phiếu KC ``finance/CIT`` posted → thôi. Ngược lại đảo
        KC năm 2026 cũ (nếu còn), ghi thêm nghiệp vụ (bỏ qua ref đã có), KC lại
        kèm ``run_cit``.
        """
        Company = self.env['res.company']
        if company is None:
            company = Company.search([('name', '=', W11_BCTC_COMPANY_NAME)], limit=1)
        if not company:
            return False
        finance_close = self.env['vas.closing.entry'].search([
            ('company_id', '=', company.id),
            ('date_from', '=', '2026-01-01'),
            ('date_to', '=', '2026-12-31'),
            ('state', '=', 'posted'),
            ('note', 'ilike', '%finance/CIT%'),
        ], limit=1)
        if finance_close:
            acc_821 = self.env.ref('connecta_vas.vas_account_tt133_821')
            amount_821, side_821 = self.env['vas.closing.rule'].compute_closing_amount(
                acc_821, company, '2026-01-01', '2026-12-31', 'both',
            )
            if float_is_zero(amount_821 or 0.0, precision_digits=2):
                return True
            # Phiếu cũ ghi CIT trên cùng KC mà chưa xả 821→911 — đảo để KC lại
            finance_close.action_reverse_entry()

        # Đảo mọi KC năm 2026 đang posted (bản cũ không CIT / finance)
        old_entries = self.env['vas.closing.entry'].search([
            ('company_id', '=', company.id),
            ('date_from', '=', '2026-01-01'),
            ('date_to', '=', '2026-12-31'),
            ('state', '=', 'posted'),
        ])
        for entry in old_entries:
            entry.action_reverse_entry()

        regime = company.vas_regime_id
        journal = self.env['vas.journal'].search([
            ('company_id', '=', company.id), ('code', '=', 'TH'),
        ], limit=1)

        def acc(code):
            return self.env.ref('connecta_vas.vas_account_tt133_%s' % code)

        def post_lines(date_str, lines, ref):
            existing = self.env['vas.move'].search([
                ('company_id', '=', company.id),
                ('ref', '=', ref),
                ('is_reversal', '=', False),
                ('state', 'not in', ('reversed', 'cancelled')),
            ], limit=1)
            if existing:
                return existing
            move = self.env['vas.move'].create({
                'date': date_str,
                'journal_id': journal.id,
                'regime_id': regime.id,
                'company_id': company.id,
                'ref': ref,
                'move_kind': 'manual',
                'line_ids': [
                    (0, 0, {
                        'account_id': a.id,
                        'name': ref,
                        'debit': deb,
                        'credit': cre,
                        'partner_id': p.id if p else False,
                    }) for a, deb, cre, p in lines
                ],
            })
            move.action_post()
            return move

        # (a) Giải ngân vay + thẻ vas.loan → trích lãi thật (loan_interest)
        bank = self.env['res.partner'].search([
            ('name', '=', 'W11 NH cho vay'),
            ('company_id', 'in', (False, company.id)),
        ], limit=1)
        if not bank:
            bank = self.env['res.partner'].create({
                'name': 'W11 NH cho vay',
                'company_id': company.id,
                'is_company': True,
            })
        post_lines('2026-06-01', [
            (acc('111'), 100_000_000, 0, False),
            (acc('3411'), 0, 100_000_000, bank),
        ], 'W11 giải ngân vay')

        loan = self.env['vas.loan'].search([
            ('company_id', '=', company.id),
            ('code', '=', 'W11-VAY-01'),
        ], limit=1)
        if not loan:
            loan = self.env['vas.loan'].create({
                'code': 'W11-VAY-01',
                'name': 'Vay W11 thử BCTC',
                'company_id': company.id,
                'regime_id': regime.id,
                'partner_id': bank.id,
                'date_start': '2026-06-01',
                'date_end': '2026-06-30',
                'principal': 100_000_000,
                'interest_rate': 0.12,
                'day_count_basis': '30_360',
                'interest_balance_mode': 'period_start',
                'account_loan_id': acc('3411').id,
                'account_interest_expense_id': acc('635').id,
                'account_interest_payable_id': acc('335').id,
                'journal_id': journal.id,
            })
            loan.action_confirm()
        elif loan.state == 'draft':
            loan.action_confirm()
        period_jun = self.env['vas.period'].search([
            ('fiscalyear_id.company_id', '=', company.id),
            ('date_start', '=', '2026-06-01'),
        ], limit=1)
        self.env['vas.loan'].generate_interest_entries(company, period_jun)
        interest_line = loan.line_ids.filtered(
            lambda l: l.period_id == period_jun and l.state == 'posted'
        )[:1]
        if (
            not interest_line
            or float_compare(interest_line.amount, W11_BCTC_LOAN_INTEREST, 2) != 0
        ):
            raise ValueError(
                'W11 loan interest expected %s got %s'
                % (W11_BCTC_LOAN_INTEREST, interest_line.amount if interest_line else None)
            )

        # (b) Doanh thu tài chính 515
        post_lines('2026-08-15', [
            (acc('111'), W11_BCTC_FINANCE_INCOME, 0, False),
            (acc('515'), 0, W11_BCTC_FINANCE_INCOME, False),
        ], 'W11 lãi tiền gửi')

        # (c) 635 không phải lãi vay — chiết khấu thanh toán (tiền)
        post_lines('2026-09-10', [
            (acc('635'), W11_BCTC_NON_INTEREST_635, 0, False),
            (acc('111'), 0, W11_BCTC_NON_INTEREST_635, False),
        ], W11_BCTC_FINANCE_REF)

        # (d) Thu nhập / chi phí khác
        post_lines('2026-10-05', [
            (acc('111'), W11_BCTC_OTHER_INCOME, 0, False),
            (acc('711'), 0, W11_BCTC_OTHER_INCOME, False),
        ], 'W11 thu nhập khác')
        post_lines('2026-10-20', [
            (acc('811'), W11_BCTC_OTHER_EXPENSE, 0, False),
            (acc('111'), 0, W11_BCTC_OTHER_EXPENSE, False),
        ], 'W11 chi phí khác')

        # (e) Thuế TNDN — kế toán nhập số (W10): ghi Nợ 821 / Có 3334 trước KC.
        # Không dùng run_cit trên cùng phiếu: lớp A chỉ đọc số đã post nên
        # 821→911 (year_end_bctc) sẽ bỏ sót dòng B_cit chưa ghi sổ.
        post_lines('2026-12-31', [
            (acc('821'), W11_BCTC_CIT_AMOUNT, 0, False),
            (acc('3334'), 0, W11_BCTC_CIT_AMOUNT, False),
        ], 'W11 thuế TNDN tạm tính')

        entry = self.env['vas.closing.entry'].create({
            'company_id': company.id,
            'date_from': '2026-01-01',
            'date_to': '2026-12-31',
            'run_kqkd': True,
            'run_year_start': False,
            'run_fx': False,
            'run_vat': False,
            'run_prepaid': False,
            'run_manual': False,
            'run_cit': False,
            'note': 'W11 BCTC demo year-end close + finance/CIT',
        })
        entry.action_fetch_data()
        entry.action_post()
        return True

    @api.model
    def _vas_w11_bctc_cashflow_label_for_move(self, vas_move):
        """Suy nhãn LCTT demo từ narration/ref — không đoán theo TK."""
        name = (vas_move.narration or vas_move.ref or '').strip()
        ref = vas_move.ref or ''
        if name == 'Góp vốn':
            return 'financing', 'capital_receipt', False
        if name in ('Mua TSCĐ', 'A28 mua TSCĐ VH 2113', 'A28 XDCB dở dang 2412'):
            return 'investing', False, False
        if ref == 'W11 giải ngân vay' or name == 'W11 giải ngân vay':
            return 'financing', 'loan_receipt', True
        if name == 'W11 lãi tiền gửi':
            return 'investing', False, False
        if name in ('W11 thu nhập khác', 'W11 chi phí khác'):
            # Khớp mã 06 (B02 31/32) — phần tiền vào mã 22 (chưa đủ TL/NB)
            return 'investing', False, False
        if name == 'A28 TG có kỳ hạn 12811':
            return 'investing', False, False
        if ref == W11_BCTC_FINANCE_REF:
            return 'operating', False, False
        if name in (
            'Trả một phần NCC A', 'Trả trước NCC B',
            'Thu một phần KH A', 'KH B trả trước',
            'CP bán hàng', 'CP QLDN',
            'A28 tạm ứng NV 141',
            'A28 phải thu nội bộ 1368', 'A28 DT HH trên 5111',
            'Mua HH NCC A',
        ):
            return 'operating', False, False
        return False, False, False

    @api.model
    def _vas_w11_ensure_odoo_cash_journal(self, company):
        """Journal quỹ/NH Odoo + TK outstanding tối thiểu — tạo nhãn LCTT không cần CoA đầy đủ."""
        # account.payment.create cần outstanding (chart ref hoặc transfer_account_id)
        if not company.transfer_account_id:
            Account = self.env['account.account']
            outstanding = Account.search([
                ('company_ids', 'in', company.id),
                ('account_type', 'in', ('asset_cash', 'asset_current')),
                ('code', 'in', ('W11.OUT', '1111', '111')),
            ], limit=1)
            if not outstanding:
                outstanding = Account.create({
                    'name': 'W11 outstanding (nhãn LCTT)',
                    'code': 'W11.OUT',
                    'account_type': 'asset_current',
                    'reconcile': True,
                    'company_ids': [Command.link(company.id)],
                })
            company.sudo().write({'transfer_account_id': outstanding.id})

        journal = self.env['account.journal'].search([
            ('type', 'in', ('cash', 'bank')),
            ('company_id', '=', company.id),
        ], limit=1)
        if journal:
            return journal
        return self.env['account.journal'].create({
            'name': 'W11 quỹ nhãn LCTT',
            'code': 'W11C',
            'type': 'cash',
            'company_id': company.id,
        })

    @api.model
    def _vas_w11_link_cashflow_carrier(
        self, company, vas_move, activity, op_type=False, loan_id=False,
    ):
        """Tạo draft account.payment nhãn LCTT + gắn source vas.move (SQL)."""
        if vas_move.source_model in (
            'account.payment', 'vas.debt.offset',
        ) and vas_move.source_res_id:
            src = self.env[vas_move.source_model].browse(
                vas_move.source_res_id,
            ).exists()
            if src and src.vas_cash_flow_activity:
                return src

        journal = self._vas_w11_ensure_odoo_cash_journal(company)

        cash_lines = vas_move.line_ids.filtered(
            lambda l: l.account_id.code.startswith('111')
            or l.account_id.code.startswith('112'),
        )
        net = sum(cash_lines.mapped(lambda l: l.debit - l.credit))
        if float_is_zero(net, precision_digits=2):
            return False

        partner = company.partner_id
        vals = {
            'payment_type': 'inbound' if net > 0 else 'outbound',
            'partner_type': 'customer',
            'partner_id': partner.id,
            'amount': abs(net),
            'date': vas_move.date,
            'journal_id': journal.id,
            'memo': W11_BCTC_CF_LABEL_REF,
            'vas_cash_flow_activity': activity,
        }
        if op_type:
            vals['vas_operation_type'] = op_type
        if loan_id:
            loan = self.env['vas.loan'].search([
                ('company_id', '=', company.id),
                ('code', '=', 'W11-VAY-01'),
            ], limit=1)
            if loan:
                vals['vas_loan_id'] = loan.id

        payment = self.env['account.payment'].create(vals)
        self.env.flush_all()
        self.env.cr.execute(
            """
            UPDATE vas_move
               SET source_model = %s, source_res_id = %s
             WHERE id = %s
            """,
            ('account.payment', payment.id, vas_move.id),
        )
        vas_move.invalidate_recordset(['source_model', 'source_res_id'])
        return payment

    @api.model
    def _vas_w11_ensure_bctc_demo_cashflow_labels(self, company=None):
        """Gắn nhãn LCTT trên chứng từ Odoo cho PS quỹ W11 — idempotent."""
        Company = self.env['res.company']
        if company is None:
            company = Company.search([('name', '=', W11_BCTC_COMPANY_NAME)], limit=1)
        if not company:
            return False

        regime = company.vas_regime_id
        journal = self.env['vas.journal'].search([
            ('company_id', '=', company.id), ('code', '=', 'TH'),
        ], limit=1)

        def acc(code):
            return self.env.ref('connecta_vas.vas_account_tt133_%s' % code)

        def post_cash_move(date_str, lines, ref, move_kind='manual'):
            existing = self.env['vas.move'].search([
                ('company_id', '=', company.id),
                ('ref', '=', ref),
                ('is_reversal', '=', False),
                ('state', 'not in', ('reversed', 'cancelled')),
            ], limit=1)
            if existing:
                return existing
            move = self.env['vas.move'].create({
                'date': date_str,
                'journal_id': journal.id,
                'regime_id': regime.id,
                'company_id': company.id,
                'ref': ref,
                'move_kind': move_kind,
                'line_ids': [
                    (0, 0, {
                        'account_id': a.id,
                        'name': ref,
                        'debit': deb,
                        'credit': cre,
                    }) for a, deb, cre in lines
                ],
            })
            move.action_post()
            return move

        # (1) Chi trả lãi vay tiền mặt → mã 15
        int_move = post_cash_move('2026-11-15', [
            (acc('335'), W11_BCTC_LOAN_INTEREST, 0),
            (acc('111'), 0, W11_BCTC_LOAN_INTEREST),
        ], W11_BCTC_PAY_INTEREST_REF, move_kind='loan_interest_pay')
        pay_int = self.env['account.payment'].search([
            ('memo', '=', W11_BCTC_PAY_INTEREST_REF),
            ('company_id', '=', company.id),
        ], limit=1)
        if not pay_int:
            bank = self._vas_w11_ensure_odoo_cash_journal(company)
            loan = self.env['vas.loan'].search([
                ('company_id', '=', company.id),
                ('code', '=', 'W11-VAY-01'),
            ], limit=1)
            pay_int = self.env['account.payment'].create({
                'payment_type': 'outbound',
                'partner_type': 'supplier',
                'partner_id': company.partner_id.id,
                'amount': W11_BCTC_LOAN_INTEREST,
                'date': '2026-11-15',
                'journal_id': bank.id,
                'memo': W11_BCTC_PAY_INTEREST_REF,
                'vas_operation_type': 'loan_interest_pay',
                'vas_cash_flow_activity': 'operating',
                'vas_loan_id': loan.id if loan else False,
            })
        self.env.flush_all()
        self.env.cr.execute(
            """
            UPDATE vas_move
               SET source_model = %s, source_res_id = %s
             WHERE id = %s
            """,
            ('account.payment', pay_int.id, int_move.id),
        )
        int_move.invalidate_recordset(['source_model', 'source_res_id'])

        # (2) Nộp TNDN tiền mặt → mã 16
        cit_move = post_cash_move('2026-12-20', [
            (acc('3334'), W11_BCTC_CIT_AMOUNT, 0),
            (acc('111'), 0, W11_BCTC_CIT_AMOUNT),
        ], W11_BCTC_PAY_CIT_REF)
        pay_cit = self.env['account.payment'].search([
            ('memo', '=', W11_BCTC_PAY_CIT_REF),
            ('company_id', '=', company.id),
        ], limit=1)
        if not pay_cit:
            bank = self._vas_w11_ensure_odoo_cash_journal(company)
            pay_cit = self.env['account.payment'].create({
                'payment_type': 'outbound',
                'partner_type': 'supplier',
                'partner_id': company.partner_id.id,
                'amount': W11_BCTC_CIT_AMOUNT,
                'date': '2026-12-20',
                'journal_id': bank.id,
                'memo': W11_BCTC_PAY_CIT_REF,
                'vas_cash_flow_activity': 'operating',
            })
        self.env.flush_all()
        self.env.cr.execute(
            """
            UPDATE vas_move
               SET source_model = %s, source_res_id = %s
             WHERE id = %s
            """,
            ('account.payment', pay_cit.id, cit_move.id),
        )
        cit_move.invalidate_recordset(['source_model', 'source_res_id'])

        # (3) Nhãn cho mọi vas.move PS quỹ còn thiếu activity nguồn
        cash_accs = self.env['vas.account'].search([
            ('regime_id', '=', regime.id),
            '|', ('code', '=like', '111%'), ('code', '=like', '112%'),
        ])
        if not cash_accs:
            return True
        cash_line_moves = self.env['vas.move.line'].search([
            ('company_id', '=', company.id),
            ('account_id', 'in', cash_accs.ids),
            ('move_id.move_kind', '!=', 'opening'),
            ('move_id.state', '=', 'posted'),
            ('move_id.is_reversal', '=', False),
        ]).mapped('move_id')

        for vm in cash_line_moves:
            activity, op_type, need_loan = self._vas_w11_bctc_cashflow_label_for_move(vm)
            if not activity:
                continue
            if vm.source_model in (
                'account.payment', 'vas.debt.offset',
            ) and vm.source_res_id:
                src = self.env[vm.source_model].browse(vm.source_res_id).exists()
                if src:
                    write_vals = {}
                    if src.vas_cash_flow_activity != activity:
                        write_vals['vas_cash_flow_activity'] = activity
                    if op_type and getattr(src, 'vas_operation_type', None) != op_type:
                        write_vals['vas_operation_type'] = op_type
                    if write_vals:
                        src.write(write_vals)
                    continue
            self._vas_w11_link_cashflow_carrier(
                company, vm, activity,
                op_type=op_type or False,
                loan_id=need_loan,
            )

        return True
