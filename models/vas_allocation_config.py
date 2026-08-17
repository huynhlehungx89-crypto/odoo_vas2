# -*- coding: utf-8 -*-
"""Cấu hình phân bổ chi phí chung (W12 Chặng 2 — HM8)."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare


ALLOCATION_CRITERIA = [
    ('named', 'Đích danh'),
    ('material_value', 'Theo tiền nguyên vật liệu thực dùng'),
    ('output_qty', 'Theo số lượng sản phẩm làm ra'),
    ('hours', 'Theo giờ công hoặc giờ máy'),
    ('bom_norm', 'Theo định mức tiêu hao nguyên vật liệu'),
    ('manual_factor', 'Theo hệ số tự nhập'),
]

ALLOCATION_SCOPES = [
    ('company', 'Toàn công ty'),
    ('workshop', 'Theo phân xưởng'),
    ('process', 'Theo quy trình'),
    ('parent_object', 'Theo đối tượng cha'),
]


class VasAllocationConfig(models.Model):
    _name = 'vas.allocation.config'
    _description = 'Cấu hình phân bổ chi phí chung'
    _order = 'cost_item_id, sequence, date_from, id'

    name = fields.Char(
        string='Tên',
        compute='_compute_name',
        store=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Công ty',
        required=True,
        index=True,
        ondelete='restrict',
        default=lambda self: self.env.company,
    )
    cost_item_id = fields.Many2one(
        'vas.cost.item',
        string='Khoản mục chi phí',
        required=True,
        index=True,
        ondelete='restrict',
        domain="[('is_aggregate_node', '=', False), ('code', '!=', 'CPD'), "
               "('company_id', '=', company_id)]",
    )
    scope_type = fields.Selection(
        selection=ALLOCATION_SCOPES,
        string='Phạm vi',
        required=True,
        default='company',
        index=True,
    )
    scope_object_id = fields.Many2one(
        'vas.cost.object',
        string='Bản ghi phạm vi',
        index=True,
        ondelete='restrict',
        help='Bắt buộc khi phạm vi khác toàn công ty.',
    )
    criterion = fields.Selection(
        selection=ALLOCATION_CRITERIA,
        string='Tiêu thức chia',
        required=True,
        default='manual_factor',
    )
    sequence = fields.Integer(
        string='Thứ tự chạy',
        required=True,
        default=1,
        help='1 hoặc 2. Lớn hơn 2 bị chặn ở tầng dữ liệu.',
    )
    date_from = fields.Date(string='Hiệu lực từ ngày', required=True)
    date_to = fields.Date(string='Hiệu lực đến ngày')
    active = fields.Boolean(string='Đang dùng', default=True)
    factor_ids = fields.One2many(
        'vas.allocation.config.factor',
        'config_id',
        string='Hệ số theo đối tượng',
    )
    currency_id = fields.Many2one(
        related='company_id.currency_id',
        readonly=True,
    )

    @api.depends('cost_item_id', 'scope_type', 'sequence', 'date_from')
    def _compute_name(self):
        scope_label = dict(ALLOCATION_SCOPES)
        for row in self:
            item = row.cost_item_id.code if row.cost_item_id else '?'
            scope = scope_label.get(row.scope_type, row.scope_type or '')
            row.name = _('%(item)s · %(scope)s · TT%(seq)s · từ %(from)s') % {
                'item': item,
                'scope': scope,
                'seq': row.sequence or 0,
                'from': row.date_from or '',
            }

    @api.onchange('scope_type')
    def _onchange_scope_type(self):
        for row in self:
            if row.scope_type == 'workshop':
                row.scope_type = 'company'
                return {
                    'warning': {
                        'title': _('Phạm vi chưa mở'),
                        'message': _(
                            'Chưa có đường nối — không chọn được phạm vi '
                            '«Theo phân xưởng».'
                        ),
                    },
                }
            if row.scope_type == 'company':
                row.scope_object_id = False

    @api.constrains('cost_item_id')
    def _check_cost_item_leaf_not_cpd(self):
        for row in self:
            item = row.cost_item_id
            if not item:
                continue
            if item.is_aggregate_node:
                raise ValidationError(_(
                    'Cấu hình phân bổ chỉ nhận khoản mục lá. '
                    '«%(code)s — %(name)s» là nút tổng hợp.',
                    code=item.code or '',
                    name=item.name or '',
                ))
            if item._is_cpd_seed():
                raise ValidationError(_(
                    'Không được khai khoản mục «Chưa phân loại» (CPD) trên '
                    'cấu hình phân bổ.'
                ))

    @api.constrains('scope_type', 'scope_object_id')
    def _check_scope(self):
        for row in self:
            if row.scope_type == 'workshop':
                raise ValidationError(_(
                    'Chưa có đường nối — không chọn được phạm vi «Theo phân xưởng».'
                ))
            if row.scope_type != 'company' and not row.scope_object_id:
                raise ValidationError(_(
                    'Phạm vi «%(scope)s» bắt buộc chọn bản ghi phạm vi.',
                    scope=dict(ALLOCATION_SCOPES).get(row.scope_type),
                ))
            if row.scope_type == 'company' and row.scope_object_id:
                raise ValidationError(_(
                    'Phạm vi toàn công ty không được chọn bản ghi phạm vi.'
                ))
            if row.scope_type == 'process' and row.scope_object_id:
                if row.scope_object_id.object_type != 'process':
                    raise ValidationError(_(
                        'Bản ghi phạm vi «Theo quy trình» phải là đối tượng loại '
                        'Quy trình sản xuất.'
                    ))
            if row.scope_type == 'parent_object' and row.scope_object_id:
                if row.scope_object_id.company_id != row.company_id:
                    raise ValidationError(_(
                        'Bản ghi phạm vi phải thuộc cùng công ty với dòng cấu hình.'
                    ))

    @api.constrains('sequence')
    def _check_sequence_max(self):
        for row in self:
            if row.sequence is False or row.sequence is None:
                continue
            if row.sequence < 1 or row.sequence > 2:
                raise ValidationError(_(
                    'Thứ tự chạy chỉ được là 1 hoặc 2. Giá trị vừa nhập: %(val)s.',
                    val=row.sequence,
                ))

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for row in self:
            if row.date_from and row.date_to and row.date_to < row.date_from:
                raise ValidationError(_(
                    'Ngày hiệu lực đến phải sau hoặc bằng ngày hiệu lực từ.'
                ))

    @api.constrains(
        'cost_item_id', 'scope_type', 'scope_object_id', 'sequence',
        'date_from', 'date_to', 'company_id', 'active',
    )
    def _check_no_overlap(self):
        """Chồng hiệu lực = cùng khoản mục + phạm vi + bản ghi phạm vi + thứ tự chạy.

        Thứ tự chạy nằm trong khóa: vòng 1 và vòng 2 (sequence 1 vs 2) phải cùng tồn tại
        trên cùng khoản mục / phạm vi / khoảng ngày — thiếu sequence thì vòng 2 bị chặn oan.
        """
        for row in self:
            if not row.active or not row.cost_item_id or not row.date_from:
                continue
            domain = [
                ('id', '!=', row.id),
                ('active', '=', True),
                ('company_id', '=', row.company_id.id),
                ('cost_item_id', '=', row.cost_item_id.id),
                ('scope_type', '=', row.scope_type),
                ('scope_object_id', '=', row.scope_object_id.id
                 if row.scope_object_id else False),
                ('sequence', '=', row.sequence),
            ]
            rivals = self.search(domain)
            for other in rivals:
                if self._dates_overlap(
                    row.date_from, row.date_to,
                    other.date_from, other.date_to,
                ):
                    raise ValidationError(_(
                        'Cấu hình phân bổ chồng khoảng hiệu lực.\n'
                        'Dòng hiện tại: %(a)s (%(af)s → %(at)s).\n'
                        'Dòng xung đột: %(b)s (%(bf)s → %(bt)s).',
                        a=row.display_name,
                        af=row.date_from,
                        at=row.date_to or _('(không hạn)'),
                        b=other.display_name,
                        bf=other.date_from,
                        bt=other.date_to or _('(không hạn)'),
                    ))

    @api.constrains(
        'cost_item_id', 'scope_type', 'scope_object_id',
        'date_from', 'date_to', 'company_id', 'active',
    )
    def _check_no_parent_child_same_window(self):
        """Quy tắc 4 mục 4.1: không khai đồng thời cha và con cùng phạm vi + hiệu lực."""
        for row in self:
            if not row.active or not row.cost_item_id:
                continue
            item = row.cost_item_id
            relatives = item.child_ids | item.parent_id
            if not relatives:
                continue
            rivals = self.search([
                ('id', '!=', row.id),
                ('active', '=', True),
                ('company_id', '=', row.company_id.id),
                ('cost_item_id', 'in', relatives.ids),
                ('scope_type', '=', row.scope_type),
                ('scope_object_id', '=', row.scope_object_id.id
                 if row.scope_object_id else False),
            ])
            for other in rivals:
                if self._dates_overlap(
                    row.date_from, row.date_to,
                    other.date_from, other.date_to,
                ):
                    raise ValidationError(_(
                        'Không được khai cấu hình phân bổ đồng thời ở khoản mục '
                        'cha và con trong cùng phạm vi và cùng khoảng hiệu lực.\n'
                        'Cha/con: %(a)s ↔ %(b)s.',
                        a=item.code,
                        b=other.cost_item_id.code,
                    ))

    @api.model
    def _dates_overlap(self, a_from, a_to, b_from, b_to):
        a_end = a_to or fields.Date.to_date('9999-12-31')
        b_end = b_to or fields.Date.to_date('9999-12-31')
        return a_from <= b_end and b_from <= a_end

    def action_export_factors_xlsx(self):
        """Xuất hệ số ra file Excel (CSV mở được bằng Excel)."""
        self.ensure_one()
        import base64
        import io
        buf = io.StringIO()
        buf.write('code,name,factor\n')
        for line in self.factor_ids.sorted(
            lambda l: (l.cost_object_id.code or '', l.cost_object_id.id),
        ):
            buf.write('%s,%s,%s\n' % (
                line.cost_object_id.code or '',
                (line.cost_object_id.name or '').replace(',', ' '),
                line.factor,
            ))
        data = base64.b64encode(buf.getvalue().encode('utf-8'))
        att = self.env['ir.attachment'].create({
            'name': 'he_so_phan_bo_%s.csv' % (self.cost_item_id.code or self.id),
            'type': 'binary',
            'datas': data,
            'mimetype': 'text/csv',
            'res_model': self._name,
            'res_id': self.id,
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % att.id,
            'target': 'self',
        }

    def action_open_factor_import(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Nhập hệ số Excel/CSV'),
            'res_model': 'vas.allocation.factor.import.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_config_id': self.id},
        }


class VasAllocationConfigFactor(models.Model):
    _name = 'vas.allocation.config.factor'
    _description = 'Hệ số tự nhập theo đối tượng'
    _order = 'cost_object_id, id'

    config_id = fields.Many2one(
        'vas.allocation.config',
        string='Cấu hình',
        required=True,
        index=True,
        ondelete='cascade',
    )
    cost_object_id = fields.Many2one(
        'vas.cost.object',
        string='Đối tượng',
        required=True,
        index=True,
        ondelete='restrict',
    )
    factor = fields.Float(
        string='Hệ số',
        required=True,
        digits=(16, 10),
        default=0.0,
    )
    company_id = fields.Many2one(
        related='config_id.company_id',
        store=True,
        index=True,
    )

    _config_object_uniq = models.Constraint(
        'UNIQUE(config_id, cost_object_id)',
        'Mỗi đối tượng chỉ khai một hệ số trên một dòng cấu hình.',
    )

    @api.constrains('factor')
    def _check_factor_non_negative(self):
        for row in self:
            if float_compare(row.factor, 0.0, precision_digits=10) < 0:
                raise ValidationError(_(
                    'Cấm tiêu thức âm. Hệ số của đối tượng «%(code)s» = %(val)s.',
                    code=row.cost_object_id.code or '',
                    val=row.factor,
                ))


class VasAllocationFactorImportWizard(models.TransientModel):
    _name = 'vas.allocation.factor.import.wizard'
    _description = 'Nhập hệ số phân bổ từ CSV/Excel'

    config_id = fields.Many2one(
        'vas.allocation.config',
        string='Cấu hình',
        required=True,
        ondelete='cascade',
    )
    data_file = fields.Binary(string='Tệp CSV', required=True)
    filename = fields.Char(string='Tên tệp')

    def action_import(self):
        self.ensure_one()
        import base64
        import csv
        import io
        raw = base64.b64decode(self.data_file)
        text = raw.decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(text))
        Factor = self.env['vas.allocation.config.factor']
        Object = self.env['vas.cost.object']
        created = 0
        for row in reader:
            code = (row.get('code') or row.get('Code') or '').strip()
            if not code:
                continue
            factor_s = (row.get('factor') or row.get('Factor') or '0').strip()
            try:
                factor = float(factor_s)
            except ValueError as err:
                raise UserError(_(
                    'Hệ số không hợp lệ ở mã %(code)s: %(val)s',
                    code=code, val=factor_s,
                )) from err
            if float_compare(factor, 0.0, precision_digits=10) < 0:
                raise UserError(_(
                    'Cấm tiêu thức âm (mã %(code)s = %(val)s).',
                    code=code, val=factor,
                ))
            obj = Object.search([
                ('code', '=', code),
                ('company_id', '=', self.config_id.company_id.id),
            ], limit=1)
            if not obj:
                raise UserError(_(
                    'Không tìm thấy đối tượng mã %(code)s.',
                    code=code,
                ))
            existing = Factor.search([
                ('config_id', '=', self.config_id.id),
                ('cost_object_id', '=', obj.id),
            ], limit=1)
            if existing:
                existing.factor = factor
            else:
                Factor.create({
                    'config_id': self.config_id.id,
                    'cost_object_id': obj.id,
                    'factor': factor,
                })
            created += 1
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Đã nhập hệ số'),
                'message': _('Đã xử lý %(n)s dòng.', n=created),
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
