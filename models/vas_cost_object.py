# -*- coding: utf-8 -*-
"""Đối tượng tập hợp chi phí + ma trận / whitelist nguồn (W12 Chặng 1A)."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class VasCostObjectSourceMap(models.Model):
    """Whitelist bảng nguồn theo loại đối tượng — khai bằng dữ liệu (4.5 điều kiện 1)."""

    _name = 'vas.cost.object.source.map'
    _description = 'Bảng nguồn hợp lệ theo loại đối tượng'
    _order = 'object_type, model_name, id'

    object_type = fields.Selection(
        selection='_selection_all_object_types',
        string='Loại đối tượng',
        required=True,
    )
    model_name = fields.Char(string='Tên bảng nguồn', required=True)
    unique_per_company = fields.Boolean(
        string='Nguồn duy nhất theo công ty',
        default=True,
        help='Chặn hai đối tượng cùng công ty nối cùng một bản ghi nguồn.',
    )
    active = fields.Boolean(default=True)

    _type_model_uniq = models.Constraint(
        'UNIQUE(object_type, model_name)',
        'Mỗi cặp loại đối tượng / bảng nguồn chỉ khai một lần.',
    )

    @api.model
    def _selection_all_object_types(self):
        return [
            ('product', 'Sản phẩm'),
            ('operation', 'Công đoạn'),
            ('process', 'Quy trình sản xuất'),
            ('workshop', 'Phân xưởng'),
            ('project', 'Công trình'),
            ('sale_order', 'Đơn hàng'),
            ('contract', 'Hợp đồng'),
        ]


class VasCostObjectParentMatrix(models.Model):
    """Ma trận cha–con hợp lệ theo loại — khai bằng dữ liệu (4.2)."""

    _name = 'vas.cost.object.parent.matrix'
    _description = 'Ma trận quan hệ cha–con đối tượng tập hợp chi phí'
    _order = 'parent_type, child_type, id'

    parent_type = fields.Selection(
        selection='_selection_all_object_types',
        string='Loại cha',
        required=True,
    )
    child_type = fields.Selection(
        selection='_selection_all_object_types',
        string='Loại con',
        required=True,
    )
    active = fields.Boolean(default=True)

    _parent_child_uniq = models.Constraint(
        'UNIQUE(parent_type, child_type)',
        'Mỗi cặp loại cha–con chỉ khai một lần.',
    )

    @api.model
    def _selection_all_object_types(self):
        return VasCostObjectSourceMap._selection_all_object_types(self)


class VasCostObject(models.Model):
    _name = 'vas.cost.object'
    _description = 'Đối tượng tập hợp chi phí'
    _parent_name = 'parent_id'
    _parent_store = True
    _rec_name = 'complete_name'
    _order = 'complete_name, id'

    code = fields.Char(string='Mã', required=True, index=True)
    name = fields.Char(string='Tên', required=True)
    complete_name = fields.Char(
        string='Tên đầy đủ',
        compute='_compute_complete_name',
        recursive=True,
        store=True,
    )
    object_type = fields.Selection(
        selection='_selection_object_type',
        string='Loại',
        required=True,
        index=True,
    )
    parent_id = fields.Many2one(
        'vas.cost.object',
        string='Đối tượng cha',
        index=True,
        ondelete='restrict',
    )
    parent_path = fields.Char(index=True)
    child_ids = fields.One2many(
        'vas.cost.object', 'parent_id', string='Đối tượng con',
    )
    # Nguồn nối mềm — ba trường (4.5). Không dùng fields.Reference.
    source_model = fields.Char(string='Tên bảng nguồn', index=True, copy=False)
    source_res_id = fields.Integer(string='Mã bản ghi nguồn', index=True, copy=False)
    source_label_snapshot = fields.Char(
        string='Nguồn nối',
        copy=False,
        help='Bản chụp nhãn nghiệp vụ — thứ duy nhất hiện cho người dùng.',
    )
    source_status = fields.Selection(
        selection=[
            ('none', 'Không có nguồn'),
            ('alive', 'Còn tồn tại'),
            ('orphan', 'Nguồn không còn tồn tại'),
        ],
        string='Trạng thái nguồn',
        default='none',
        index=True,
        copy=False,
        help='Cập nhật khi tạo/đổi nguồn, đồng bộ danh mục, hoặc bấm làm mới — không ghi mỗi lần đọc.',
    )
    # UI chọn biến thể (product luôn có trong depends). Không dùng Many2one mrp.*.
    ui_product_id = fields.Many2one(
        'product.product',
        string='Biến thể sản phẩm',
        compute='_compute_ui_product_id',
        inverse='_inverse_ui_product_id',
        store=False,
    )
    wip_account_id = fields.Many2one(
        'vas.account',
        string='Tài khoản dở dang',
        required=True,
        ondelete='restrict',
        default=lambda self: self._default_account_154(),
    )
    active = fields.Boolean(string='Đang dùng', default=True)
    company_id = fields.Many2one(
        'res.company',
        string='Công ty',
        required=True,
        index=True,
        ondelete='restrict',
        default=lambda self: self.env.company,
    )
    is_aggregate_node = fields.Boolean(
        string='Nút tổng hợp',
        compute='_compute_is_aggregate_node',
        store=True,
    )

    _code_company_uniq = models.Constraint(
        'UNIQUE(code, company_id)',
        'Mã đối tượng tập hợp chi phí phải duy nhất theo công ty.',
    )

    @api.model
    def _default_account_154(self):
        company = self.env.company
        regime = company.vas_regime_id
        if not regime:
            return False
        return self.env['vas.account'].search([
            ('regime_id', '=', regime.id),
            ('code', '=', '154'),
        ], limit=1)

    @api.model
    def _mrp_available(self):
        return 'mrp.bom' in self.env

    @api.model
    def _selection_object_type(self):
        """Ẩn công đoạn / quy trình khi chưa có module Sản xuất."""
        types = [
            ('product', _('Sản phẩm')),
            ('workshop', _('Phân xưởng')),
            ('project', _('Công trình')),
            ('sale_order', _('Đơn hàng')),
            ('contract', _('Hợp đồng')),
        ]
        if self._mrp_available():
            types = [
                ('product', _('Sản phẩm')),
                ('operation', _('Công đoạn')),
                ('process', _('Quy trình sản xuất')),
                ('workshop', _('Phân xưởng')),
                ('project', _('Công trình')),
                ('sale_order', _('Đơn hàng')),
                ('contract', _('Hợp đồng')),
            ]
        return types

    @api.depends('name', 'parent_id.complete_name')
    def _compute_complete_name(self):
        for obj in self:
            if obj.parent_id:
                obj.complete_name = '%s / %s' % (
                    obj.parent_id.complete_name, obj.name,
                )
            else:
                obj.complete_name = obj.name

    @api.depends('child_ids')
    def _compute_is_aggregate_node(self):
        for obj in self:
            obj.is_aggregate_node = bool(obj.child_ids)

    @api.depends('source_model', 'source_res_id')
    def _compute_ui_product_id(self):
        for obj in self:
            if (
                obj.source_model == 'product.product'
                and obj.source_res_id
                and 'product.product' in self.env
            ):
                obj.ui_product_id = self.env['product.product'].browse(
                    obj.source_res_id,
                ).exists()
            else:
                obj.ui_product_id = False

    def _inverse_ui_product_id(self):
        for obj in self:
            if obj.object_type != 'product':
                continue
            if not obj.ui_product_id:
                obj.write({
                    'source_model': False,
                    'source_res_id': 0,
                    'source_label_snapshot': False,
                    'source_status': 'none',
                })
                continue
            obj._apply_source_link('product.product', obj.ui_product_id.id)

    # ---- nguồn nối mềm -------------------------------------------------

    @api.model
    def _allowed_source_maps(self, object_type):
        return self.env['vas.cost.object.source.map'].search([
            ('object_type', '=', object_type),
            ('active', '=', True),
        ])

    @api.model
    def _allowed_source_models(self, object_type):
        """Danh sách bảng hợp lệ theo loại — chép logic Reference (selection)."""
        maps = self._allowed_source_maps(object_type)
        models = []
        for m in maps:
            # Chỉ liệt kê bảng đang có trong registry (module nguồn còn).
            if m.model_name in self.env:
                models.append(m.model_name)
        return models

    @api.model
    def _build_source_label(self, record):
        """Bản chụp nhãn nghiệp vụ từ bản ghi nguồn."""
        if not record:
            return False
        code = False
        for attr in ('default_code', 'code', 'display_name'):
            val = getattr(record, attr, False)
            if val and attr != 'display_name':
                code = val
                break
        name = record.display_name or ''
        if code and code != name:
            return '%s — %s' % (code, name)
        return name

    @api.model
    def _source_record_company_id(self, record):
        if not record:
            return False
        if 'company_id' in record._fields:
            return record.company_id.id if record.company_id else False
        if (
            record._name == 'mrp.routing.workcenter'
            and 'bom_id' in record._fields
            and record.bom_id
            and 'company_id' in record.bom_id._fields
        ):
            return (
                record.bom_id.company_id.id
                if record.bom_id.company_id else False
            )
        return False

    def _compute_source_status_value(self):
        self.ensure_one()
        if not self.source_model or not self.source_res_id:
            return 'none'
        if self.source_model not in self.env:
            return 'orphan'
        record = self.env[self.source_model].browse(self.source_res_id).exists()
        return 'alive' if record else 'orphan'

    def _apply_source_link(self, model_name, res_id):
        """Ghi nguồn nối — write sẽ kiểm tồn tại / công ty / trùng và cập nhật bản chụp."""
        self.ensure_one()
        if not model_name or not res_id:
            return self.write({
                'source_model': False,
                'source_res_id': 0,
                'source_label_snapshot': False,
                'source_status': 'none',
            })
        return self.write({
            'source_model': model_name,
            'source_res_id': res_id,
        })

    def action_refresh_source_label(self):
        """Người dùng bấm làm mới — một trong ba thời điểm cập nhật bản chụp."""
        for obj in self:
            if not obj.source_model or not obj.source_res_id:
                obj.source_status = 'none'
                continue
            if obj.source_model not in self.env:
                obj.source_status = 'orphan'
                continue
            record = self.env[obj.source_model].browse(
                obj.source_res_id,
            ).exists()
            if not record:
                obj.source_status = 'orphan'
                continue
            obj.write({
                'source_label_snapshot': self._build_source_label(record),
                'source_status': 'alive',
            })
        return True

    def action_sync_catalog_check(self):
        """Lượt kiểm tra đồng bộ danh mục — cập nhật trạng thái (+ bản chụp nếu còn sống)."""
        targets = self or self.search([])
        for obj in targets:
            status = obj._compute_source_status_value()
            vals = {'source_status': status}
            if status == 'alive':
                record = self.env[obj.source_model].browse(
                    obj.source_res_id,
                ).exists()
                vals['source_label_snapshot'] = self._build_source_label(record)
            # orphan / none: snapshot đóng băng, không xóa.
            obj.write(vals)
        return True

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec, vals in zip(records, vals_list):
            if vals.get('source_model') or vals.get('source_res_id'):
                # create đã ghi raw — chuẩn hóa snapshot/status một lần.
                rec._validate_and_refresh_source(refresh_snapshot=True)
            elif rec.object_type == 'product' and not rec.source_model:
                pass
            else:
                if not rec.source_model:
                    rec.source_status = 'none'
        return records

    def write(self, vals):
        if 'parent_id' in vals:
            parent_id = vals.get('parent_id') or False
            if parent_id and isinstance(parent_id, models.BaseModel):
                parent_id = parent_id.id
            self._assert_no_parent_cycle(parent_id)
        source_changed = (
            'source_model' in vals
            or 'source_res_id' in vals
            or 'object_type' in vals
        )
        res = super().write(vals)
        if source_changed:
            for rec in self:
                rec._validate_and_refresh_source(refresh_snapshot=True)
        return res

    def _validate_and_refresh_source(self, refresh_snapshot=False):
        """Kiểm 2–5 lúc tạo/sửa + cập nhật trạng thái/bản chụp khi cần."""
        self.ensure_one()
        maps = self._allowed_source_maps(self.object_type)
        allowed_models = maps.mapped('model_name')

        if not self.source_model or not self.source_res_id:
            # Phân xưởng / loại chưa mở: không bắt buộc nguồn.
            # Chỉ dọn meta nguồn — không đụng snapshot nếu vốn đã trống.
            if (
                self.source_status != 'none'
                or self.source_label_snapshot
                or self.source_model
                or self.source_res_id
            ):
                super(VasCostObject, self).write({
                    'source_status': 'none',
                    'source_label_snapshot': False,
                    'source_model': False,
                    'source_res_id': 0,
                })
            return

        if self.source_model not in allowed_models:
            raise ValidationError(_(
                'Loại đối tượng «%(type)s» không được nối bảng «%(model)s».',
                type=dict(self._selection_object_type()).get(
                    self.object_type, self.object_type,
                ),
                model=self.source_model,
            ))

        if self.source_model not in self.env:
            # Module nguồn bị gỡ — không sai im lặng: đánh orphan, giữ snapshot.
            super(VasCostObject, self).write({'source_status': 'orphan'})
            return

        record = self.env[self.source_model].browse(
            self.source_res_id,
        ).exists()
        if not record:
            # Lúc tạo/sửa nguồn mà không tồn tại → chặn (không tạo liên kết mồ côi mới).
            raise ValidationError(_(
                'Bản ghi nguồn %(model)s (id=%(id)s) không còn tồn tại.',
                model=self.source_model,
                id=self.source_res_id,
            ))
        src_company = self._source_record_company_id(record)
        if src_company and src_company != self.company_id.id:
            raise ValidationError(_(
                'Nguồn nối phải thuộc cùng công ty với đối tượng tập hợp chi phí.'
            ))
        # Chặn nối trùng nguồn (điều kiện 4).
        map_rec = maps.filtered(
            lambda m: m.model_name == self.source_model
        )[:1]
        if map_rec and map_rec.unique_per_company:
            rivals = self.search([
                ('id', '!=', self.id),
                ('company_id', '=', self.company_id.id),
                ('source_model', '=', self.source_model),
                ('source_res_id', '=', self.source_res_id),
            ], limit=1)
            if rivals:
                raise ValidationError(_(
                    'Nguồn %(model)s (id=%(id)s) đã được nối với đối tượng '
                    '«%(code)s — %(name)s» trong cùng công ty.',
                    model=self.source_model,
                    id=self.source_res_id,
                    code=rivals.code,
                    name=rivals.name,
                ))
        vals = {'source_status': 'alive'}
        if refresh_snapshot:
            vals['source_label_snapshot'] = self._build_source_label(record)
        super(VasCostObject, self).write(vals)

    # ---- cha–con --------------------------------------------------------

    @api.constrains('parent_id')
    def _check_object_recursion(self):
        if self._has_cycle():
            raise ValidationError(_(
                'Không được tạo vòng lặp cha–con trên đối tượng tập hợp chi phí.'
            ))

    def _assert_no_parent_cycle(self, new_parent_id):
        """Chặn vòng lặp TRƯỚC parent_store (tránh lỗi Anh «Recursion Detected»)."""
        if not new_parent_id:
            return
        for obj in self:
            if new_parent_id == obj.id:
                raise ValidationError(_(
                    'Không được tạo vòng lặp cha–con trên đối tượng tập hợp chi phí.'
                ))
            if obj.id and self.search_count([
                ('id', '=', new_parent_id),
                ('id', 'child_of', obj.id),
            ]):
                raise ValidationError(_(
                    'Không được tạo vòng lặp cha–con trên đối tượng tập hợp chi phí.'
                ))

    @api.constrains('parent_id', 'object_type')
    def _check_parent_matrix(self):
        Matrix = self.env['vas.cost.object.parent.matrix']
        for obj in self:
            if not obj.parent_id:
                continue
            allowed = Matrix.search([
                ('parent_type', '=', obj.parent_id.object_type),
                ('child_type', '=', obj.object_type),
                ('active', '=', True),
            ], limit=1)
            if not allowed:
                raise ValidationError(_(
                    'Quan hệ cha–con không hợp lệ: «%(parent)s» (%(ptype)s) '
                    'không được làm cha của «%(child)s» (%(ctype)s). '
                    'Đợt này chỉ mở: quy trình sản xuất làm cha của công đoạn.',
                    parent=obj.parent_id.code,
                    ptype=obj.parent_id.object_type,
                    child=obj.code,
                    ctype=obj.object_type,
                ))

    def _unlink_usage_messages(self):
        messages = []
        Period = self.env['vas.costing.period']
        for obj in self:
            parts = []
            children = self.search([('parent_id', '=', obj.id)])
            if children:
                parts.append(_(
                    '%(n)s đối tượng con (%(codes)s)',
                    n=len(children),
                    codes=', '.join(children.mapped('code')),
                ))
            periods = Period.search([('cost_object_ids', 'in', obj.ids)])
            if periods:
                parts.append(_(
                    '%(n)s kỳ tính giá thành (%(names)s)',
                    n=len(periods),
                    names=', '.join(periods.mapped('name')),
                ))
            if parts:
                messages.append(_(
                    'Không xóa được đối tượng %(code)s — %(name)s.\n'
                    'Đang được dùng bởi: %(usage)s.\n'
                    'Việc cần làm: gỡ khỏi kỳ / chuyển đối tượng con, '
                    'hoặc ngừng dùng thay vì xóa.',
                    code=obj.code,
                    name=obj.name,
                    usage='; '.join(parts),
                ))
        return messages

    def unlink(self):
        for msg in self._unlink_usage_messages():
            raise UserError(msg)
        return super().unlink()
