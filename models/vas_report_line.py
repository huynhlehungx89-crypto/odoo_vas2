# -*- coding: utf-8 -*-
"""Chỉ tiêu BCTC — khai bằng dữ liệu (tầng 4), bảo vệ seed qua ir.model.data."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


AMOUNT_SOURCE_SELECTION = [
    ('balance', 'Số dư'),
    ('turnover', 'Số phát sinh'),
    ('total', 'Tổng chỉ tiêu con'),
    ('force_zero', 'Buộc 0 (theo ĐVTT)'),
    ('code_custom', 'Tính riêng bằng code'),
]

TURNOVER_MODE_SELECTION = [
    ('gross', 'Phát sinh trần'),
    ('counterpart', 'Phát sinh đối ứng'),
]

BALANCE_SIDE_SELECTION = [
    ('debit', 'Nợ (chi tiết)'),
    ('credit', 'Có (chi tiết)'),
    ('signed_credit', 'Có mang dấu (dư Nợ → âm)'),
    ('signed_debit', 'Nợ mang dấu (dư Có → âm)'),
]

TURNOVER_SIDE_SELECTION = [
    ('debit', 'Nợ'),
    ('credit', 'Có'),
]

LINE_ROLE_SELECTION = [
    ('detail', 'Chi tiết'),
    ('total', 'Tổng'),
]

BASIS_KIND_SELECTION = [
    ('trich_tt133', 'Trích TT133'),
    ('suy_ket_cau', 'Suy từ kết cấu'),
    ('chot_connecta', 'Chốt Connecta'),
    ('trich_tt133_chot_connecta', 'Trích TT133 + Chốt Connecta'),
]

WARN_KIND_SELECTION = [
    ('none', 'Không'),
    ('balance_on_codes', 'Cảnh báo nếu TK còn số dư'),
    ('residual_413_vnd', 'Cảnh báo 413 còn SD khi ĐVTT = VND'),
]

B09_FILL_KIND_SELECTION = [
    ('section', 'Mục khung'),
    ('machine_now', 'Máy lấy được ngay'),
    ('machine_gap', 'Máy lấy được nếu bổ sung dữ liệu'),
    ('manual', 'Kế toán tự điền'),
    ('na', 'Không áp dụng'),
]

B09_TABLE_STATUS_SELECTION = [
    ('full', 'Máy điền đủ'),
    ('total_ok_detail_open', 'Máy điền được phần tổng, các dòng chi tiết còn mở'),
    ('none_yet', 'Máy chưa lấy được số'),
    ('manual_all', 'Kế toán tự điền toàn bộ'),
]


class VasReportLine(models.Model):
    _name = 'vas.report.line'
    _description = 'Chỉ tiêu báo cáo tài chính VAS'
    _order = 'form_code, sequence, code, id'

    sequence = fields.Integer(string='Thứ tự in', default=10, required=True)
    code = fields.Char(string='Mã số chỉ tiêu', required=True, index=True)
    name = fields.Char(string='Tên chỉ tiêu', required=True)
    form_code = fields.Char(
        string='Mẫu',
        required=True,
        index=True,
        help='Ví dụ B01a-DNN.',
    )
    regime_id = fields.Many2one(
        'vas.regime',
        string='Chế độ kế toán',
        required=True,
        index=True,
        ondelete='restrict',
    )
    line_role = fields.Selection(
        selection=LINE_ROLE_SELECTION,
        string='Cấp bậc',
        required=True,
        default='detail',
    )
    amount_source = fields.Selection(
        selection=AMOUNT_SOURCE_SELECTION,
        string='Cách lấy số',
        required=True,
        default='balance',
    )
    turnover_mode = fields.Selection(
        selection=TURNOVER_MODE_SELECTION,
        string='Loại phát sinh',
        help='Chỉ dùng khi Cách lấy số = Số phát sinh: trần hoặc đối ứng.',
    )
    balance_side = fields.Selection(
        selection=BALANCE_SIDE_SELECTION,
        string='Bên Nợ/Có',
    )
    account_codes = fields.Char(
        string='Danh sách tài khoản',
        help='Mã TK cách nhau bởi dấu phẩy. Không gộp con tự động — khai đủ cha/con.',
    )
    source_side = fields.Selection(
        selection=TURNOVER_SIDE_SELECTION,
        string='Bên TK nguồn (PS)',
        help='Bên Nợ/Có của tài khoản nguồn khi lấy phát sinh.',
    )
    counterpart_account_codes = fields.Char(
        string='Tài khoản đối ứng',
        help='Mã TK đối ứng cách nhau bởi dấu phẩy (vd 911 hoặc 111,112,131).',
    )
    counterpart_side = fields.Selection(
        selection=TURNOVER_SIDE_SELECTION,
        string='Bên TK đối ứng',
        help='Bên Nợ/Có của tài khoản đối ứng trên cùng chứng từ.',
    )
    counterpart_net_both_ways = fields.Boolean(
        string='Đối ứng hai chiều (có dấu)',
        default=False,
        help='Ví dụ mã 51: Có↔Nợ dương trừ Nợ↔Có âm.',
    )
    code_custom_key = fields.Char(
        string='Khóa tính riêng bằng code',
        help='Khi Cách lấy số = Tính riêng bằng code — khóa công thức '
             '(vd b02_loan_interest; B09: b09_from_b01a:110, b09_unavailable). '
             'Khai trong dữ liệu, không ẩn.',
    )
    aggregate_by_partner = fields.Boolean(
        string='Cộng theo từng đối tác',
        default=False,
        help='TT133 công nợ: cộng SD chi tiết theo từng đối tác rồi gom. '
             'Dư Nợ → chỉ tiêu bên tài sản; dư Có → bên nguồn vốn. '
             'Dòng không có đối tác không tự xếp — chỉ cảnh báo.',
    )
    child_line_ids = fields.Many2many(
        'vas.report.line',
        'vas_report_line_child_rel',
        'parent_id',
        'child_id',
        string='Chỉ tiêu con',
        help='Chỉ tiêu tổng = tổng các chỉ tiêu con (quan hệ dữ liệu).',
        domain="[('form_code', '=', form_code), ('regime_id', '=', regime_id)]",
    )
    show_negative_paren = fields.Boolean(
        string='Âm trong ngoặc',
        default=False,
    )
    sign_negative = fields.Boolean(
        string='Đảo dấu khi cộng',
        default=False,
        help='Dự phòng / CP quỹ: lấy SD Có rồi đảo dấu để trừ vào tổng.',
    )
    basis_kind = fields.Selection(
        selection=BASIS_KIND_SELECTION,
        string='Loại căn cứ',
        required=True,
        default='trich_tt133',
    )
    basis_note = fields.Char(string='Ghi chú căn cứ')
    warn_kind = fields.Selection(
        selection=WARN_KIND_SELECTION,
        string='Loại cảnh báo',
        required=True,
        default='none',
    )
    warn_account_codes = fields.Char(
        string='TK cảnh báo số dư',
        help='Ví dụ 1281,1288 hoặc 1361.',
    )
    warn_message = fields.Char(string='Nội dung cảnh báo')
    force_zero_currency_id = fields.Many2one(
        'res.currency',
        string='Buộc 0 khi ĐVTT',
        help='Khi currency công ty trùng → số chỉ tiêu = 0 (mã 415 / C5).',
    )
    b09_fill_kind = fields.Selection(
        selection=B09_FILL_KIND_SELECTION,
        string='Phân loại điền B09',
        help='Chỉ dùng form B09-DNN: máy ngay / thiếu data / nhập tay / không áp dụng.',
    )
    b09_gap_reason = fields.Char(
        string='Thiếu gì (B09)',
        help='Khi phân loại = máy lấy được nếu bổ sung dữ liệu.',
    )
    b09_table_status = fields.Selection(
        selection=B09_TABLE_STATUS_SELECTION,
        string='Trạng thái bảng B09',
        help='Trên dòng mục bảng: trạng thái hiển thị tại chỗ.',
    )
    b09_table_status_note = fields.Char(
        string='Ghi chú trạng thái bảng B09',
    )
    note_b09_code = fields.Char(
        string='Thuyết minh (mã mục B09)',
        index=True,
        help='Mã chỉ tiêu B09 ổn định (vd V.1.total) — cột Thuyết minh trên '
             'B01a/B02. Để trống nếu không có mục tương ứng. Không dùng số thứ tự.',
    )
    active = fields.Boolean(string='Đang dùng', default=True)
    is_system = fields.Boolean(
        string='Chỉ tiêu hệ thống',
        default=False,
        help='Seed: nhận diện thật qua ir.model.data, không tin riêng field này.',
    )

    _code_form_regime_uniq = models.Constraint(
        'UNIQUE(regime_id, form_code, code)',
        'Mã chỉ tiêu phải duy nhất theo mẫu và chế độ kế toán.',
    )

    def _xml_seed_rules(self):
        """Seed module ``connecta_vas`` — nhận diện qua ``ir.model.data``."""
        if not self:
            return self.browse()
        self.env.cr.execute(
            """
            SELECT res_id FROM ir_model_data
             WHERE module = 'connecta_vas'
               AND model = 'vas.report.line'
               AND res_id = ANY(%s)
            """,
            [list(self.ids)],
        )
        seed_ids = {row[0] for row in self.env.cr.fetchall()}
        return self.filtered(lambda r: r.id in seed_ids)

    _SEED_STRUCTURAL_FIELDS = frozenset({
        'code', 'form_code', 'regime_id', 'line_role', 'amount_source',
        'turnover_mode', 'balance_side', 'account_codes',
        'source_side', 'counterpart_account_codes', 'counterpart_side',
        'counterpart_net_both_ways', 'code_custom_key',
        'aggregate_by_partner',
        'child_line_ids', 'show_negative_paren',
        'sign_negative', 'basis_kind', 'warn_kind', 'warn_account_codes',
        'force_zero_currency_id',
        'b09_fill_kind', 'b09_gap_reason', 'b09_table_status', 'b09_table_status_note',
    })

    def write(self, vals):
        seed = self._xml_seed_rules()
        if seed and 'is_system' in vals and not vals.get('is_system'):
            raise UserError(_(
                'Không được bỏ nhãn hệ thống của chỉ tiêu báo cáo do module cài đặt. '
                'Chỉ được bật/tắt hoặc sửa tên / thứ tự / ghi chú.'
            ))
        protected = self.filtered('is_system') | seed
        if protected:
            hit = sorted(self._SEED_STRUCTURAL_FIELDS.intersection(vals))
            if hit:
                for field in hit:
                    new_val = vals[field]
                    for line in protected:
                        old = line[field]
                        if field == 'child_line_ids':
                            raise UserError(_(
                                'Không được đổi quan hệ chỉ tiêu con của chỉ tiêu '
                                'hệ thống (seed module).'
                            ))
                        if field == 'force_zero_currency_id':
                            old_cmp = old.id if old else False
                            new_cmp = (
                                new_val.id if hasattr(new_val, 'id')
                                else (new_val or False)
                            )
                        elif field == 'regime_id':
                            old_cmp = old.id if old else False
                            new_cmp = (
                                new_val.id if hasattr(new_val, 'id')
                                else (new_val or False)
                            )
                        else:
                            old_cmp = old
                            new_cmp = new_val
                        if old_cmp != new_cmp:
                            raise UserError(_(
                                'Không được đổi field cấu trúc (%(fields)s) của chỉ tiêu '
                                'báo cáo hệ thống. Chỉ được bật/tắt hoặc sửa tên / thứ tự.',
                                fields=', '.join(hit),
                            ))
        return super().write(vals)

    def unlink(self):
        seed = self._xml_seed_rules()
        protected = self.filtered('is_system') | seed
        if protected:
            raise UserError(_(
                'Không được xóa chỉ tiêu báo cáo hệ thống (seed module). '
                'Chỉ được bật/tắt hoặc sửa tên / thứ tự.'
            ))
        return super().unlink()

    def copy(self, default=None):
        self.ensure_one()
        default = dict(default or {})
        default.setdefault('is_system', False)
        default.setdefault('active', False)
        if 'code' not in default:
            default['code'] = _('%s-copy') % (self.code or 'line')
        return super().copy(default)

    @api.model
    def _parse_codes(self, codes_char):
        if not codes_char:
            return []
        return [c.strip() for c in codes_char.split(',') if c.strip()]
