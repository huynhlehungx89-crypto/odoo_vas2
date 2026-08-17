# -*- coding: utf-8 -*-
"""W10 — quy tắc kết chuyển + hàm tính số dư thuần (chưa cắm wizard)."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare, float_is_zero, float_round


CLOSE_SIDE_SELECTION = [
    ('debit', 'Nợ'),
    ('credit', 'Có'),
    ('both', 'Hai bên (số dư thuần)'),
]

RULE_LAYER_SELECTION = [
    ('A_close', 'Lớp A — Kết chuyển số dư'),
    ('B_accrual', 'Lớp B — Trích/phân bổ/dự phòng'),
    ('B_vat', 'Lớp B — Khấu trừ GTGT (L06)'),
    ('B_fx', 'Lớp B — Đánh giá lại NT (V09)'),
    ('B_cit', 'Lớp B — Thuế TNDN'),
    ('B_costing', 'Lớp B — Giá thành'),
]

GROUP_CODE_SELECTION = [
    ('kqkd', 'KQKD / 911'),
    ('fx', 'Chênh lệch tỷ giá'),
    ('vat', 'GTGT'),
    ('cit', 'Thuế TNDN'),
    ('provision', 'Dự phòng / trích trước'),
    ('prepaid', 'Phân bổ 242 / 3387'),
    ('costing', 'Giá thành / KK định kỳ'),
    ('year_start', 'Đầu năm 4212→4211'),
]

TIMING_SELECTION = [
    ('period_end', 'Cuối kỳ'),
    ('year_end_bctc', 'Khi lập BCTC năm'),
    ('year_start', 'Đầu năm tài chính'),
    ('after_fx_reval', 'Sau đánh giá lại NT'),
]


class VasClosingRule(models.Model):
    _name = 'vas.closing.rule'
    _description = 'Quy tắc kết chuyển cuối kỳ'
    _order = 'sequence, id'

    # P4 — chế độ lấy số dư TK nguồn.
    # False (hiện tại): chỉ đúng account_id — CHO phép rule cha 511 + lá 5111 cùng active.
    # True (cấm bật một mình): gộp mọi tiểu khoản con → rule cha+lá XẢ ĐÔI;
    #   constraint K10 cha-con bên dưới mới bắt. Đổi cờ này PHẢI sửa luôn
    #   compute_closing_amount + seed (tắt cha hoặc tắt lá) — đừng chỉ đổi một chỗ.
    _AGGREGATE_CHILDREN_OF_FROM = False

    sequence = fields.Integer(string='Thứ tự', default=10, required=True)
    code = fields.Char(string='Mã', required=True, index=True)
    name = fields.Char(string='Diễn giải', required=True)
    regime_id = fields.Many2one(
        'vas.regime',
        string='Chế độ kế toán',
        required=True,
        index=True,
        ondelete='restrict',
    )
    rule_layer = fields.Selection(
        selection=RULE_LAYER_SELECTION,
        string='Lớp',
        required=True,
        index=True,
    )
    account_from_id = fields.Many2one(
        'vas.account',
        string='TK nguồn',
        ondelete='restrict',
        index=True,
    )
    account_to_id = fields.Many2one(
        'vas.account',
        string='TK đích',
        ondelete='restrict',
        index=True,
    )
    close_side = fields.Selection(
        selection=CLOSE_SIDE_SELECTION,
        string='Bên kết chuyển',
        help='both = số dư thuần một dòng, chiều theo dấu (∑Nợ − ∑Có).',
    )
    group_code = fields.Selection(
        selection=GROUP_CODE_SELECTION,
        string='Nhóm',
        required=True,
        index=True,
    )
    timing = fields.Selection(
        selection=TIMING_SELECTION,
        string='Thời điểm',
        required=True,
        default='period_end',
    )
    active = fields.Boolean(string='Đang dùng', default=True)
    is_system = fields.Boolean(
        string='Quy tắc hệ thống',
        default=False,
        help='Seed hệ thống: không sửa TK nguồn/đích; cho bật/tắt và sửa diễn giải.',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Công ty',
        ondelete='cascade',
        index=True,
        help='Trống = áp mọi công ty cùng chế độ. Override theo công ty: dùng mã rule riêng.',
    )

    _code_regime_uniq = models.Constraint(
        'UNIQUE(regime_id, code)',
        'Mã quy tắc kết chuyển phải duy nhất theo chế độ kế toán.',
    )

    def _xml_seed_rules(self):
        """Rule seed module ``connecta_vas`` — nhận diện qua ``ir.model.data``,

        không dựa vào field ``is_system`` (tránh đường lách hạ nhãn rồi đổi TK).
        """
        if not self:
            return self.browse()
        self.env.cr.execute(
            """
            SELECT res_id FROM ir_model_data
             WHERE module = 'connecta_vas'
               AND model = 'vas.closing.rule'
               AND res_id = ANY(%s)
            """,
            [list(self.ids)],
        )
        seed_ids = {row[0] for row in self.env.cr.fetchall()}
        return self.filtered(lambda r: r.id in seed_ids)

    # Field cấu trúc — đổi là làm rule seed mất đúng nghĩa (K9).
    # Cho phép: active, sequence, name (thiết kế §2.1).
    _SEED_STRUCTURAL_FIELDS = frozenset({
        'account_from_id', 'account_to_id', 'regime_id', 'company_id',
        'rule_layer', 'close_side', 'timing', 'code',
    })

    def write(self, vals):
        seed = self._xml_seed_rules()
        # Seed hệ thống: không cho hạ is_system (độc lập với giá trị hiện tại).
        if seed and 'is_system' in vals and not vals.get('is_system'):
            raise UserError(_(
                'Không được bỏ nhãn hệ thống của quy tắc kết chuyển do module cài đặt. '
                'Chỉ được bật/tắt hoặc sửa diễn giải / thứ tự.'
            ))
        protected = self.filtered('is_system') | seed
        if protected:
            hit = sorted(self._SEED_STRUCTURAL_FIELDS.intersection(vals))
            if hit:
                # Chỉ chặn khi giá trị thực sự đổi
                for field in hit:
                    new_val = vals[field]
                    for rule in protected:
                        old = rule[field]
                        old_cmp = old.id if hasattr(old, 'id') else old
                        new_cmp = new_val
                        if field in (
                            'account_from_id', 'account_to_id',
                            'regime_id', 'company_id',
                        ):
                            old_cmp = old.id if old else False
                            new_cmp = new_val.id if hasattr(new_val, 'id') else (new_val or False)
                        if new_cmp != old_cmp:
                            raise UserError(_(
                                'Không được đổi field cấu trúc (%(fields)s) của quy tắc '
                                'kết chuyển hệ thống. Chỉ được bật/tắt hoặc sửa diễn giải / thứ tự.',
                                fields=', '.join(hit),
                            ))
        return super().write(vals)

    def unlink(self):
        seed = self._xml_seed_rules()
        protected = self.filtered('is_system') | seed
        if protected:
            raise UserError(_(
                'Không được xóa quy tắc kết chuyển hệ thống (seed module). '
                'Chỉ được bật/tắt hoặc sửa diễn giải / thứ tự.'
            ))
        return super().unlink()

    def copy(self, default=None):
        """Bản sao = rule khách (không phải seed). Cho sửa — seed gốc vẫn khóa.

        Mặc định ``active=False`` để tránh ngay lập tức trùng TK nguồn với gốc (K10).
        """
        self.ensure_one()
        default = dict(default or {})
        default.setdefault('is_system', False)
        default.setdefault('active', False)
        if 'code' not in default:
            default['code'] = _('%s-copy') % (self.code or 'rule')
        return super().copy(default)

    def _company_scope_overlaps(self, other):
        """True nếu hai rule có thể cùng áp cho một công ty."""
        self.ensure_one()
        if not self.company_id or not other.company_id:
            return True
        return self.company_id == other.company_id

    @api.model
    def _aggregate_children_of_from(self):
        return bool(self._AGGREGATE_CHILDREN_OF_FROM)

    @api.model
    def _account_is_ancestor(self, ancestor, descendant):
        """True nếu ``ancestor`` là cha/ông… của ``descendant`` trên cây TK."""
        if not ancestor or not descendant or ancestor == descendant:
            return False
        current = descendant.parent_id
        while current:
            if current == ancestor:
                return True
            current = current.parent_id
        return False

    def _close_sides_conflict(self, side_a, side_b):
        """Cùng chiều xả (both hoặc cùng debit/credit) → xung đột."""
        if not side_a or not side_b:
            return False
        if side_a == 'both' or side_b == 'both':
            return True
        return side_a == side_b

    def _balance_close_conflicts(self, other):
        """Hai rule active cùng lấy số dư một TK nguồn theo cách chồng nhau.

        Cho phép cặp bổ sung ``debit`` + ``credit`` (821/911/4212/413 seed).
        Chặn: cùng ``both``, hoặc cùng một phía, hoặc ``both`` lẫn phía.
        Không gộp tiểu khoản con — chỉ so khớp ``account_from_id`` (K10 đo),
        trừ khi ``_AGGREGATE_CHILDREN_OF_FROM`` (xem ``_parent_child_close_conflicts``).
        """
        self.ensure_one()
        if not (
            self.active and other.active
            and self.account_from_id and other.account_from_id
            and self.account_from_id == other.account_from_id
            and self.regime_id == other.regime_id
            and self._company_scope_overlaps(other)
        ):
            return False
        return self._close_sides_conflict(self.close_side, other.close_side)

    def _parent_child_close_conflicts(self, other):
        """K10 mở rộng: chỉ khi đang GỘP con — chặn cha+lá cùng active cùng chiều.

        Hiện ``_AGGREGATE_CHILDREN_OF_FROM=False`` → luôn False (cho phép 511 + 5111).
        """
        self.ensure_one()
        if not self._aggregate_children_of_from():
            return False
        if not (
            self.active and other.active
            and self.account_from_id and other.account_from_id
            and self.regime_id == other.regime_id
            and self._company_scope_overlaps(other)
            and self.account_from_id != other.account_from_id
        ):
            return False
        related = (
            self._account_is_ancestor(self.account_from_id, other.account_from_id)
            or self._account_is_ancestor(other.account_from_id, self.account_from_id)
        )
        if not related:
            return False
        return self._close_sides_conflict(self.close_side, other.close_side)

    @api.constrains(
        'active', 'account_from_id', 'close_side', 'regime_id', 'company_id',
    )
    def _check_no_duplicate_account_from(self):
        """K10: không hai rule active cùng xả một TK nguồn (trừ cặp Nợ/Có bổ sung).

        Khi ``_AGGREGATE_CHILDREN_OF_FROM``: chặn thêm cặp cha–con.
        """
        Rule = self.env['vas.closing.rule']
        for rule in self:
            if not rule.active or not rule.account_from_id or not rule.close_side:
                continue
            domain = [
                ('id', '!=', rule.id),
                ('active', '=', True),
                ('regime_id', '=', rule.regime_id.id),
                ('account_from_id', '!=', False),
                ('close_side', '!=', False),
            ]
            if rule.company_id:
                domain = [
                    *domain,
                    '|',
                    ('company_id', '=', False),
                    ('company_id', '=', rule.company_id.id),
                ]
            for other in Rule.search(domain):
                if rule._balance_close_conflicts(other) or rule._parent_child_close_conflicts(other):
                    raise ValidationError(_(
                        'Không bật được quy tắc «%(code)s» — trùng / chồng tài khoản nguồn '
                        '%(account)s với quy tắc đang dùng «%(other)s» (%(other_name)s).\n\n'
                        'Hai quy tắc cùng lấy số dư một tài khoản (hoặc cha–con khi gộp con) '
                        'sẽ kết chuyển hai lần. Hãy tắt một trong hai, hoặc đổi tài khoản nguồn.',
                        code=rule.code or rule.display_name,
                        account=rule.account_from_id.code,
                        other=other.code or other.display_name,
                        other_name=other.name,
                    ))

    @api.model
    def compute_closing_amount(self, account, company, date_from, date_to, close_side):
        """Số cần kết chuyển của một TK trong khoảng ngày (``domain_for_amounts``).

        :return: ``(amount, from_side)`` với ``amount >= 0`` và
                 ``from_side`` ∈ ``{'debit', 'credit'}`` — **chiều ghi trên bút toán
                 kết chuyển** tại TK nguồn (để xả số dư), không phải nhãn chiều số dư;
                 hoặc ``(0.0, False)`` nếu không có gì để KC.

        ``close_side``:
        - ``debit`` / ``credit``: chỉ phần dư phía đó
        - ``both``: số dư thuần (∑Nợ − ∑Có) **một** giá trị, chiều theo dấu
          (dư Nợ → ghi Có trên nguồn; dư Có → ghi Nợ trên nguồn). Không xả hai phía.

        **Không gộp tiểu khoản con** (``_AGGREGATE_CHILDREN_OF_FROM=False``):
        domain ``account_id = account``. Seed có cả rule cha ``511→911`` và lá
        ``5111/5112/5113/5118→911`` — an toàn vì mỗi rule chỉ xả đúng một mã.
        Nếu SAU NÀY bật gộp con: bộ rule cha+lá sẽ **XẢ ĐÔI**; constraint K10
        so ``account_from`` bằng nhau **không** bắt cha–con trừ khi
        ``_parent_child_close_conflicts`` chạy (cờ gộp = True). Đổi một phải sửa cả hai.
        """
        if not account or not company or not close_side:
            return 0.0, False
        MoveLine = self.env['vas.move.line']
        if self._aggregate_children_of_from():
            accounts = account | self.env['vas.account'].search([
                ('id', 'child_of', account.id),
            ])
            account_domain = ('account_id', 'in', accounts.ids)
        else:
            account_domain = ('account_id', '=', account.id)
        domain = [
            account_domain,
            ('company_id', '=', company.id),
            *self.env['vas.move'].domain_for_amounts(prefix='move_id'),
            ('date', '>=', date_from),
            ('date', '<=', date_to),
        ]
        rows = MoveLine._read_group(
            domain,
            groupby=[],
            aggregates=['debit:sum', 'credit:sum'],
        )
        if not rows:
            sum_debit = sum_credit = 0.0
        else:
            sum_debit = rows[0][0] or 0.0
            sum_credit = rows[0][1] or 0.0

        net = float_round(sum_debit - sum_credit, precision_digits=2)
        if close_side == 'both':
            if float_is_zero(net, precision_digits=2):
                return 0.0, False
            if float_compare(net, 0.0, precision_digits=2) > 0:
                # Dư Nợ → ghi Có trên nguồn để xả
                return abs(net), 'credit'
            return abs(net), 'debit'

        if close_side == 'debit':
            if float_compare(net, 0.0, precision_digits=2) <= 0:
                return 0.0, False
            return float_round(net, precision_digits=2), 'credit'

        if close_side == 'credit':
            if float_compare(net, 0.0, precision_digits=2) >= 0:
                return 0.0, False
            return float_round(-net, precision_digits=2), 'debit'

        raise UserError(_('Bên kết chuyển không hợp lệ: %s') % close_side)
