# -*- coding: utf-8 -*-
"""Hub / lưu đồ nghiệp vụ — chỉ điều hướng UI, không đụng sổ."""
import logging

from odoo import api, fields, models, _
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)


def _vas_ops_may_mutate(env):
    """Cho phép ghi khi cài/nâng cấp (superuser) hoặc cờ seed/test."""
    if env.is_superuser():
        return True
    return bool(env.context.get('vas_ops_allow_write'))


class VasOpsGroup(models.Model):
    _name = 'vas.ops.group'
    _description = 'Nhóm nghiệp vụ VAS'
    _order = 'sequence, id'

    code = fields.Char(required=True, index=True)
    name = fields.Char(required=True, translate=True)
    icon = fields.Char(string='Biểu tượng', help='Tên icon Font Awesome, vd. fa-money')
    sequence = fields.Integer(default=10)
    screen_kind = fields.Selection(
        [
            ('hub', 'Hub (ô rời)'),
            ('workflow', 'Workflow (chuỗi)'),
        ],
        string='Kiểu màn hình',
        required=True,
        default='hub',
    )
    state = fields.Selection(
        [
            ('ready', 'Có màn hình nhóm'),
            ('temp', 'Tạm mở màn hình hiện có'),
            ('module', 'Ẩn nếu chưa cài module'),
        ],
        string='Trạng thái',
        required=True,
        default='temp',
    )
    temp_action_xmlid = fields.Char(
        string='Mã hành động tạm',
        help='ir.actions XML id dạng module.xml_id — chỉ dùng khi state=temp.',
    )
    required_module = fields.Char(
        string='Module bắt buộc',
        help='Khi state=module: ẩn nhóm nếu module này chưa installed.',
    )
    button_ids = fields.One2many('vas.ops.button', 'group_id', string='Nút')
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint(
        'unique(code)',
        'Mã nhóm nghiệp vụ phải duy nhất.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        if not _vas_ops_may_mutate(self.env):
            raise AccessError(_(
                'Người dùng nghiệp vụ không được thêm nhóm nghiệp vụ.'
            ))
        return super().create(vals_list)

    def write(self, vals):
        if not _vas_ops_may_mutate(self.env):
            raise AccessError(_(
                'Người dùng nghiệp vụ không được sửa nhóm nghiệp vụ.'
            ))
        return super().write(vals)

    def unlink(self):
        if not _vas_ops_may_mutate(self.env):
            raise AccessError(_(
                'Người dùng nghiệp vụ không được xóa nhóm nghiệp vụ.'
            ))
        return super().unlink()

    @api.model
    def _module_installed(self, module_name):
        if not module_name:
            return True
        return bool(self.env['ir.module.module'].sudo().search_count([
            ('name', '=', module_name),
            ('state', '=', 'installed'),
        ]))

    @api.model
    def _resolve_action_xmlid(self, xmlid):
        """Tra action theo chuỗi XML id. Không thấy → False, ghi log, không raise."""
        if not xmlid or not isinstance(xmlid, str):
            return False
        xmlid = xmlid.strip()
        if '.' not in xmlid:
            _logger.warning('vas.ops: action_xmlid thiếu module: %s', xmlid)
            return False
        try:
            action = self.env['ir.actions.actions']._for_xml_id(xmlid)
        except ValueError:
            _logger.warning('vas.ops: không tìm thấy action %s', xmlid)
            return False
        except Exception:  # noqa: BLE001 — một nút sai không được vỡ màn hình
            _logger.exception('vas.ops: lỗi khi tra action %s', xmlid)
            return False
        if not action or action.get('type') == 'ir.actions.act_window_close':
            return False
        return action

    def _is_visible(self):
        self.ensure_one()
        if self.state == 'module':
            return self._module_installed(self.required_module)
        return True

    @api.model
    def get_hub_tiles(self):
        """Dữ liệu lưới «Tất cả nghiệp vụ»."""
        tiles = []
        for group in self.search([('active', '=', True)]):
            if not group._is_visible():
                continue
            tiles.append({
                'id': group.id,
                'code': group.code,
                'name': group.name,
                'icon': group.icon or 'fa-th-large',
                'state': group.state,
                'screen_kind': group.screen_kind,
            })
        return tiles

    def action_open_from_hub(self):
        """Bấm ô lưới → mở lưu đồ nhóm hoặc action tạm."""
        self.ensure_one()
        if not self._is_visible():
            return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
                'title': _('Nhóm chưa sẵn sàng'),
                'message': _('Module phụ thuộc chưa được cài.'),
                'type': 'warning',
                'sticky': False,
            }}
        if self.state == 'ready':
            return {
                'type': 'ir.actions.client',
                'tag': 'vas_ops_workflow',
                'name': self.name,
                'context': {
                    'vas_ops_group_code': self.code,
                },
            }
        action = self._resolve_action_xmlid(self.temp_action_xmlid)
        if not action:
            return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
                'title': _('Chưa mở được'),
                'message': _(
                    'Không tìm thấy hành động tạm của nhóm «%(name)s».',
                    name=self.name,
                ),
                'type': 'warning',
                'sticky': False,
            }}
        return action

    @api.model
    def get_workflow_payload(self, group_code):
        """Payload khung lưu đồ cho một nhóm."""
        group = self.search([('code', '=', group_code), ('active', '=', True)], limit=1)
        if not group or not group._is_visible():
            return {
                'group': False,
                'layout': 'empty',
                'message': _('Không tìm thấy nhóm nghiệp vụ.'),
                'process': [],
                'detached': [],
                'catalog': [],
                'report': [],
            }

        def _btn_dict(btn, include_children=True):
            action = False
            if btn.action_xmlid:
                action = group._resolve_action_xmlid(btn.action_xmlid)
            children = []
            if include_children:
                for child in btn.child_ids.sorted(lambda b: (b.sequence, b.id)):
                    child_action = (
                        group._resolve_action_xmlid(child.action_xmlid)
                        if child.action_xmlid else False
                    )
                    if child.action_xmlid and not child_action:
                        continue
                    children.append({
                        'id': child.id,
                        'label': child.label,
                        'icon': child.icon or '',
                        'has_action': bool(child_action),
                        'action_xmlid': child.action_xmlid or '',
                    })
            # Ẩn nút lá khi khai action nhưng không tra được
            if btn.action_xmlid and not action and not children and not btn.child_ids:
                return None
            # Nút cha lựa chọn: hiện nếu còn ít nhất một con hiện được
            if btn.child_ids and not children and not action:
                return None
            return {
                'id': btn.id,
                'label': btn.label,
                'icon': btn.icon or '',
                'row': btn.row,
                'sequence': btn.sequence,
                'has_action': bool(action),
                'action_xmlid': btn.action_xmlid or '',
                'next_ids': btn.next_ids.ids,
                'is_choice_parent': bool(btn.child_ids),
                'children': children,
            }

        process_src = group.button_ids.filtered(
            lambda b: b.zone == 'process' and not b.parent_id
        ).sorted(lambda b: (b.row, b.sequence, b.id))
        catalog_src = group.button_ids.filtered(
            lambda b: b.zone == 'catalog'
        ).sorted(lambda b: (b.sequence, b.id))
        report_src = group.button_ids.filtered(
            lambda b: b.zone == 'report'
        ).sorted(lambda b: (b.sequence, b.id))

        catalog = []
        for btn in catalog_src:
            data = _btn_dict(btn, include_children=False)
            if data:
                catalog.append(data)
        report = []
        for btn in report_src:
            data = _btn_dict(btn, include_children=False)
            if data:
                report.append(data)

        visible_process = process_src.filtered(lambda b: _btn_dict(b) is not None)
        linked, detached_src = self._split_chain_and_detached(visible_process)
        detached = []
        process = []
        layout = 'tiles' if group.screen_kind == 'hub' else 'chain'

        if layout == 'tiles':
            for btn in visible_process.sorted(lambda b: (b.row, b.sequence, b.id)):
                data = _btn_dict(btn)
                if data:
                    process.append(data)
        else:
            if linked and not self._is_simple_chain(linked):
                layout = 'unsupported'
            elif linked:
                for btn in self._order_simple_chain(linked):
                    data = _btn_dict(btn)
                    if data:
                        process.append(data)
                for btn in detached_src.sorted(lambda b: (b.row, b.sequence, b.id)):
                    data = _btn_dict(btn)
                    if data:
                        detached.append(data)
            else:
                # Chỉ ô rời, không chuỗi — vẽ hub, không bịa đường nối
                layout = 'tiles'
                for btn in detached_src.sorted(lambda b: (b.row, b.sequence, b.id)):
                    data = _btn_dict(btn)
                    if data:
                        process.append(data)

        message = ''
        if not process and not detached and not catalog and not report:
            message = _(
                'Nhóm «%(name)s» chưa có thao tác nào mở được. '
                'Kiểm tra module phụ thuộc hoặc cấu hình hành động.',
                name=group.name,
            )
            layout = 'empty'
        elif layout == 'unsupported':
            message = _(
                'Bố cục chuỗi chưa hỗ trợ nhánh phức tạp của nhóm «%(name)s». '
                'Không vẽ sai — vui lòng dùng ô rời hoặc chỉnh dữ liệu nút.',
                name=group.name,
            )

        return {
            'group': {
                'id': group.id,
                'code': group.code,
                'name': group.name,
                'screen_kind': group.screen_kind,
            },
            'layout': layout,
            'message': message,
            'process': process,
            'detached': detached,
            'catalog': catalog,
            'report': report,
        }

    @api.model
    def _split_chain_and_detached(self, buttons):
        """Tách chuỗi (có next/prev trong tập) và ô rời (không nối)."""
        buttons = buttons.exists()
        if not buttons:
            empty = self.env['vas.ops.button']
            return empty, empty
        by_id = {b.id: b for b in buttons}
        detached = self.env['vas.ops.button']
        linked = self.env['vas.ops.button']
        for btn in buttons:
            nxt = btn.next_ids.filtered(lambda n: n.id in by_id)
            prev = btn.prev_ids.filtered(lambda p: p.id in by_id)
            if not nxt and not prev:
                detached |= btn
            else:
                linked |= btn
        return linked, detached

    @api.model
    def _order_simple_chain(self, buttons):
        """Thứ tự topo theo next_ids; fallback sequence."""
        buttons = buttons.exists()
        if not buttons:
            return buttons
        by_id = {b.id: b for b in buttons}
        starts = [
            b for b in buttons
            if not b.prev_ids.filtered(lambda p: p.id in by_id)
        ]
        if len(starts) != 1:
            return buttons.sorted(lambda b: (b.sequence, b.id))
        ordered = self.env['vas.ops.button']
        seen = set()
        cur = starts[0]
        while cur and cur.id not in seen:
            seen.add(cur.id)
            ordered |= cur
            nxt = cur.next_ids.filtered(lambda n: n.id in by_id)[:1]
            cur = nxt[0] if nxt else False
        return ordered or buttons.sorted(lambda b: (b.sequence, b.id))

    @api.model
    def _is_simple_chain(self, buttons):
        """Chuỗi thẳng: mỗi nút ≤1 next, đúng một đầu vào, không vòng."""
        buttons = buttons.exists()
        if not buttons:
            return True
        by_id = {b.id: b for b in buttons}
        starts = []
        for btn in buttons:
            if len(btn.next_ids) > 1:
                return False
            incoming = btn.prev_ids.filtered(lambda p: p.id in by_id)
            if not incoming:
                starts.append(btn)
            if len(incoming) > 1:
                return False
        if len(starts) != 1:
            return False
        seen = set()
        cur = starts[0]
        while cur:
            if cur.id in seen:
                return False
            seen.add(cur.id)
            nxt = cur.next_ids.filtered(lambda n: n.id in by_id)[:1]
            cur = nxt[0] if nxt else False
        return len(seen) == len(buttons)

    @api.model
    def action_open_xmlid(self, xmlid):
        action = self._resolve_action_xmlid(xmlid)
        if not action:
            return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
                'title': _('Không mở được'),
                'message': _('Hành động «%s» không tồn tại hoặc chưa cài.') % (xmlid or ''),
                'type': 'warning',
                'sticky': False,
            }}
        return action

    @api.model
    def action_sync_now(self):
        """Gọi lại đồng bộ đang có — không sửa engine."""
        stats = self.env['vas.sync'].sync_company(self.env.company)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Đồng bộ VAS'),
                'message': str(stats),
                'type': 'success',
                'sticky': False,
            },
        }


class VasOpsButton(models.Model):
    _name = 'vas.ops.button'
    _description = 'Nút trong nhóm nghiệp vụ VAS'
    _order = 'zone, row, sequence, id'

    group_id = fields.Many2one(
        'vas.ops.group', required=True, ondelete='cascade', index=True,
    )
    zone = fields.Selection(
        [
            ('process', 'Bước quy trình'),
            ('catalog', 'Danh mục liên quan'),
            ('report', 'Báo cáo của nhóm'),
        ],
        required=True,
        default='process',
    )
    label = fields.Char(required=True, translate=True)
    icon = fields.Char()
    row = fields.Integer(default=1)
    sequence = fields.Integer(default=10)
    next_ids = fields.Many2many(
        'vas.ops.button',
        'vas_ops_button_next_rel',
        'button_id',
        'next_id',
        string='Nút tiếp theo',
    )
    prev_ids = fields.Many2many(
        'vas.ops.button',
        'vas_ops_button_next_rel',
        'next_id',
        'button_id',
        string='Nút trước',
    )
    parent_id = fields.Many2one(
        'vas.ops.button',
        string='Nút cha (nhóm lựa chọn)',
        ondelete='cascade',
        index=True,
    )
    child_ids = fields.One2many('vas.ops.button', 'parent_id', string='Nút con')
    action_xmlid = fields.Char(
        string='Mã hành động đích',
        help='Chuỗi module.xml_id. Để trống với nút cha nhóm lựa chọn.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        if not _vas_ops_may_mutate(self.env):
            raise AccessError(_(
                'Người dùng nghiệp vụ không được thêm nút nghiệp vụ.'
            ))
        return super().create(vals_list)

    def write(self, vals):
        if not _vas_ops_may_mutate(self.env):
            raise AccessError(_(
                'Người dùng nghiệp vụ không được sửa nút nghiệp vụ.'
            ))
        return super().write(vals)

    def unlink(self):
        if not _vas_ops_may_mutate(self.env):
            raise AccessError(_(
                'Người dùng nghiệp vụ không được xóa nút nghiệp vụ.'
            ))
        return super().unlink()
