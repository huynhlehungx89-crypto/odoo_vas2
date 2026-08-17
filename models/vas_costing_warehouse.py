# -*- coding: utf-8 -*-
"""W12 Chặng 4 — bảng khai loại phiếu / khu vực kho cho ghép giá thành phẩm."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


WAREHOUSE_STEP_MODES = [
    ('one', 'Một bước'),
    ('two', 'Hai bước'),
    ('three', 'Ba bước'),
    ('subcontract', 'Gia công thuê ngoài'),
]

# Chặng 4 chỉ mở một/hai bước; ba bước và gia công giữ chỗ mở rộng.
_STEP_MODES_OPEN = frozenset({'one', 'two'})
_STEP_MODES_BLOCKED = frozenset({'three', 'subcontract'})


class VasCostingWarehouseConfig(models.Model):
    _name = 'vas.costing.warehouse.config'
    _description = 'Cấu hình kho cho giá thành (loại phiếu / khu vực)'
    _order = 'warehouse_id, id'

    name = fields.Char(
        string='Tên', compute='_compute_name', store=True,
    )
    company_id = fields.Many2one(
        'res.company', string='Công ty', required=True, index=True,
        ondelete='restrict', default=lambda self: self.env.company,
    )
    warehouse_id = fields.Many2one(
        'stock.warehouse', string='Kho', required=True, index=True,
        ondelete='restrict', check_company=True,
        help='Định danh theo mã nội bộ bản ghi kho Odoo — khai theo từng kho.',
    )
    step_mode = fields.Selection(
        selection=WAREHOUSE_STEP_MODES,
        string='Cấu hình số bước',
        required=True,
        default='one',
        help='Một bước / hai bước: mở. Ba bước và gia công: khai trong danh sách '
             'nhưng chưa cho chọn (chặn ở tầng dữ liệu).',
    )
    fg_picking_type_id = fields.Many2one(
        'stock.picking.type',
        string='Loại phiếu nhập thành phẩm',
        required=True,
        ondelete='restrict',
        check_company=True,
        domain="[('warehouse_id', '=', warehouse_id)]",
    )
    fg_location_id = fields.Many2one(
        'stock.location',
        string='Khu vực kho thành phẩm',
        required=True,
        ondelete='restrict',
        check_company=True,
    )
    isolation_location_id = fields.Many2one(
        'stock.location',
        string='Khu vực cách ly',
        ondelete='restrict',
        check_company=True,
        help='Khai sẵn cho chặng sau (hàng chờ xử) — chưa nối engine ở Chặng 4.',
    )
    costing_sale_order = fields.Boolean(
        string='Đơn hàng tính giá thành',
        default=False,
        help='Ô đánh dấu đơn hàng thuộc phạm vi tính giá thành (dùng sau).',
    )
    posting_mode = fields.Selection(
        selection=[
            ('period_end', 'Ghi cuối kỳ'),
            ('immediate', 'Ghi ngay (giá tạm tính)'),
        ],
        string='Chế độ ghi nhận',
        required=True,
        default='period_end',
        help='Ghi cuối kỳ: một lần sau duyệt. Ghi ngay: tạm theo NVL rồi ghi bù.',
    )
    active = fields.Boolean(string='Đang dùng', default=True)
    note = fields.Text(string='Ghi chú')

    _warehouse_company_uniq = models.Constraint(
        'UNIQUE(company_id, warehouse_id)',
        'Mỗi kho chỉ khai một dòng cấu hình giá thành trong một công ty.',
    )

    @api.depends('warehouse_id', 'step_mode')
    def _compute_name(self):
        labels = dict(WAREHOUSE_STEP_MODES)
        for rec in self:
            wh = rec.warehouse_id.display_name or '?'
            rec.name = '%s — %s' % (wh, labels.get(rec.step_mode, rec.step_mode or ''))

    @api.constrains('step_mode')
    def _check_step_mode_open(self):
        for rec in self:
            if rec.step_mode in _STEP_MODES_BLOCKED:
                raise ValidationError(_(
                    'Cấu hình «%(mode)s» chưa mở trong đợt này '
                    '(chỉ Một bước và Hai bước).\n'
                    'Kho: %(wh)s. Giữ chỗ mở rộng — không chọn được.',
                    mode=dict(WAREHOUSE_STEP_MODES).get(rec.step_mode),
                    wh=rec.warehouse_id.display_name,
                ))

    @api.constrains('fg_picking_type_id', 'warehouse_id')
    def _check_picking_type_warehouse(self):
        for rec in self:
            if (
                rec.fg_picking_type_id
                and rec.warehouse_id
                and rec.fg_picking_type_id.warehouse_id
                and rec.fg_picking_type_id.warehouse_id != rec.warehouse_id
            ):
                raise ValidationError(_(
                    'Loại phiếu «%(pt)s» không thuộc kho «%(wh)s».',
                    pt=rec.fg_picking_type_id.display_name,
                    wh=rec.warehouse_id.display_name,
                ))

    @api.constrains('posting_mode', 'company_id')
    def _check_immediate_mode_periods(self):
        """Chặn chọn ghi ngay khi kỳ giá thành mở không thỏa (a)(b)."""
        for rec in self:
            if rec.posting_mode != 'immediate':
                continue
            periods = self.env['vas.costing.period'].search([
                ('company_id', '=', rec.company_id.id),
                ('state', 'not in', ('posted', 'locked')),
            ])
            for period in periods:
                try:
                    period._assert_immediate_mode_allowed()
                except UserError as err:
                    raise ValidationError(_(
                        'Không chọn chế độ ghi ngay trên kho «%(wh)s».\n%(r)s',
                        wh=rec.warehouse_id.display_name,
                        r=str(err),
                    )) from err

    def write(self, vals):
        if 'posting_mode' in vals:
            for rec in self:
                if vals['posting_mode'] == rec.posting_mode:
                    continue
                lots = self.env['vas.costing.provisional.lot'].search([
                    ('warehouse_config_id', '=', rec.id),
                    ('state', '=', 'posted'),
                ])
                if lots:
                    moves = lots.mapped('move_id').filtered(
                        lambda m: m and m.state == 'posted' and not m.is_reversal,
                    )
                    raise UserError(_(
                        'Không đổi chế độ ghi nhận của kho «%(wh)s»: còn %(n)s '
                        'bút toán ghi tạm còn hiệu lực (%(sample)s).\n'
                        'Đảo các bút toán tạm trước khi đổi chế độ.',
                        wh=rec.warehouse_id.display_name,
                        n=len(moves) or len(lots),
                        sample=', '.join(
                            (moves or lots)[:3].mapped('display_name')
                        ),
                    ))
        return super().write(vals)

    def action_post_provisional_fg(self):
        """Nút trên cấu hình kho — ủy quyền sang kỳ giá thành nháp/đang mở cùng công ty."""
        self.ensure_one()
        if self.posting_mode != 'immediate':
            raise UserError(_(
                'Kho «%s» không ở chế độ ghi ngay — không ghi tạm được.',
                self.warehouse_id.display_name,
            ))
        Period = self.env['vas.costing.period']
        period = Period.search([
            ('company_id', '=', self.company_id.id),
            ('state', 'in', ('draft', 'computed', 'pending_approval', 'approved')),
        ], order='date_from desc, id desc', limit=1)
        if not period:
            raise UserError(_(
                'Không có kỳ giá thành đang mở để ghi tạm. Tạo kỳ trước.',
            ))
        return period.action_post_provisional_fg()

    def _unlink_usage_messages(self):
        """Lớp unlink tiếng Việt — quyết định 31."""
        messages = []
        Period = self.env['vas.costing.period']
        for rec in self:
            # Kỳ đang dùng kho này qua kết quả / đối tượng sản phẩm — chặn nếu còn phiên bản
            periods = Period.search([
                ('company_id', '=', rec.company_id.id),
                ('state', 'in', (
                    'computed', 'pending_approval', 'approved', 'posted', 'locked',
                )),
            ])
            if periods:
                messages.append(_(
                    'Không xóa được cấu hình kho «%(wh)s»: còn %(n)s kỳ tính giá thành '
                    'đã tính / duyệt / ghi sổ trên cùng công ty (%(sample)s).',
                    wh=rec.warehouse_id.display_name,
                    n=len(periods),
                    sample=', '.join(periods[:3].mapped('display_name')),
                ))
        return messages

    def unlink(self):
        for msg in self._unlink_usage_messages():
            raise UserError(msg)
        return super().unlink()

    @api.model
    def _configs_for_company(self, company):
        return self.search([
            ('company_id', '=', company.id),
            ('active', '=', True),
            ('step_mode', 'in', list(_STEP_MODES_OPEN)),
        ])

    def _fg_move_domain_extra(self):
        """Điều kiện nhận diện phiếu nhập TP theo một dòng khai — một chặng, lấy trọn."""
        self.ensure_one()
        return [
            '|',
            ('picking_type_id', '=', self.fg_picking_type_id.id),
            ('location_dest_id', 'child_of', self.fg_location_id.id),
        ]
