# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Lượt 3: khai bốn nhóm Tài sản / Thuế / Vay / Vốn (noupdate seed)."""
    env = api.Environment(cr, SUPERUSER_ID, {'vas_ops_allow_write': True})
    Button = env['vas.ops.button']

    group_vals = {
        'vas_ops_group_asset': {
            'state': 'ready',
            'screen_kind': 'workflow',
            'temp_action_xmlid': False,
        },
        'vas_ops_group_tax': {
            'state': 'ready',
            'screen_kind': 'workflow',
            'temp_action_xmlid': False,
        },
        'vas_ops_group_loan': {
            'code': 'vay',
            'name': 'Vay',
            'state': 'ready',
            'screen_kind': 'workflow',
            'temp_action_xmlid': False,
        },
    }
    for xmlid, vals in group_vals.items():
        rec = env.ref('connecta_vas.%s' % xmlid, raise_if_not_found=False)
        if rec:
            rec.write(vals)

    von = env.ref('connecta_vas.vas_ops_group_von', raise_if_not_found=False)
    if not von:
        von = env['vas.ops.group'].create({
            'code': 'von',
            'name': 'Vốn',
            'icon': 'fa-pie-chart',
            'sequence': 105,
            'screen_kind': 'hub',
            'state': 'ready',
        })
        env['ir.model.data'].create({
            'name': 'vas_ops_group_von',
            'module': 'connecta_vas',
            'model': 'vas.ops.group',
            'res_id': von.id,
            'noupdate': True,
        })

    asset_group = env.ref('connecta_vas.vas_ops_group_asset')
    tax_group = env.ref('connecta_vas.vas_ops_group_tax')
    vay_group = env.ref('connecta_vas.vas_ops_group_loan')
    von_group = env.ref('connecta_vas.vas_ops_group_von')

    def _ensure_button(xmlid, vals):
        btn = env.ref('connecta_vas.%s' % xmlid, raise_if_not_found=False)
        if btn:
            btn.write(vals)
            return btn
        btn = env['vas.ops.button'].create(vals)
        env['ir.model.data'].create({
            'name': xmlid,
            'module': 'connecta_vas',
            'model': 'vas.ops.button',
            'res_id': btn.id,
            'noupdate': True,
        })
        return btn

    asset_btns = [
        ('vas_ops_btn_asset_register', {
            'group_id': asset_group.id,
            'zone': 'process',
            'label': 'Ghi tăng tài sản',
            'icon': 'fa-plus-square',
            'row': 1,
            'sequence': 10,
            'action_xmlid': 'connecta_vas.action_vas_asset',
        }),
        ('vas_ops_btn_asset_depreciate', {
            'group_id': asset_group.id,
            'zone': 'process',
            'label': 'Tính khấu hao định kỳ',
            'icon': 'fa-calendar-check-o',
            'row': 1,
            'sequence': 20,
            'action_xmlid': 'connecta_vas.action_vas_period',
        }),
        ('vas_ops_btn_asset_transfer', {
            'group_id': asset_group.id,
            'zone': 'process',
            'label': 'Điều chuyển',
            'icon': 'fa-exchange',
            'row': 1,
            'sequence': 30,
            'action_xmlid': 'connecta_vas.action_vas_asset',
        }),
        ('vas_ops_btn_asset_dispose', {
            'group_id': asset_group.id,
            'zone': 'process',
            'label': 'Ghi giảm',
            'icon': 'fa-minus-circle',
            'row': 1,
            'sequence': 40,
            'action_xmlid': 'connecta_vas.action_vas_asset',
        }),
        ('vas_ops_btn_asset_prepaid', {
            'group_id': asset_group.id,
            'zone': 'process',
            'label': 'Chi phí trả trước (242)',
            'icon': 'fa-clock-o',
            'row': 2,
            'sequence': 90,
            'action_xmlid': 'connecta_vas.action_vas_asset',
        }),
        ('vas_ops_btn_asset_cat_period', {
            'group_id': asset_group.id,
            'zone': 'catalog',
            'label': 'Kỳ kế toán',
            'icon': 'fa-calendar',
            'sequence': 10,
            'action_xmlid': 'connecta_vas.action_vas_period',
        }),
    ]
    for xmlid, vals in asset_btns:
        _ensure_button(xmlid, vals)

    reg = env.ref('connecta_vas.vas_ops_btn_asset_register')
    dep = env.ref('connecta_vas.vas_ops_btn_asset_depreciate')
    trf = env.ref('connecta_vas.vas_ops_btn_asset_transfer')
    dis = env.ref('connecta_vas.vas_ops_btn_asset_dispose')
    reg.write({'next_ids': [(6, 0, [dep.id])]})
    dep.write({'next_ids': [(6, 0, [trf.id])]})
    trf.write({'next_ids': [(6, 0, [dis.id])]})

    tax_btns = [
        ('vas_ops_btn_tax_l06', {
            'group_id': tax_group.id,
            'zone': 'process',
            'label': 'Khấu trừ GTGT (L06)',
            'icon': 'fa-file-text-o',
            'row': 1,
            'sequence': 10,
            'action_xmlid': 'connecta_vas.action_vas_closing_entry',
        }),
        ('vas_ops_btn_tax_pay', {
            'group_id': tax_group.id,
            'zone': 'process',
            'label': 'Nộp thuế GTGT',
            'icon': 'fa-sign-out',
            'row': 1,
            'sequence': 20,
            'action_xmlid': 'account.action_account_payments_payable',
        }),
        ('vas_ops_btn_tax_import_vat', {
            'group_id': tax_group.id,
            'zone': 'process',
            'label': 'GTGT hàng nhập khẩu',
            'icon': 'fa-ship',
            'row': 2,
            'sequence': 90,
            'action_xmlid': 'connecta_vas.action_vas_import_vat',
        }),
        ('vas_ops_btn_tax_cat_landed', {
            'group_id': tax_group.id,
            'zone': 'catalog',
            'label': 'Ánh xạ thuế hàng NK',
            'icon': 'fa-map',
            'sequence': 10,
            'action_xmlid': 'connecta_vas.action_vas_landed_tax_map',
        }),
    ]
    for xmlid, vals in tax_btns:
        _ensure_button(xmlid, vals)
    l06 = env.ref('connecta_vas.vas_ops_btn_tax_l06')
    pay = env.ref('connecta_vas.vas_ops_btn_tax_pay')
    l06.write({'next_ids': [(6, 0, [pay.id])]})

    vay_btns = [
        ('vas_ops_btn_loan_contract', {
            'group_id': vay_group.id,
            'zone': 'process',
            'label': 'Khế ước vay',
            'icon': 'fa-file-text',
            'row': 1,
            'sequence': 10,
            'action_xmlid': 'connecta_vas.action_vas_loan',
        }),
        ('vas_ops_btn_loan_schedule', {
            'group_id': vay_group.id,
            'zone': 'process',
            'label': 'Lịch trả lãi',
            'icon': 'fa-calendar',
            'row': 1,
            'sequence': 20,
            'action_xmlid': 'connecta_vas.action_vas_loan',
        }),
        ('vas_ops_btn_loan_accrue', {
            'group_id': vay_group.id,
            'zone': 'process',
            'label': 'Ghi lãi định kỳ',
            'icon': 'fa-percent',
            'row': 1,
            'sequence': 30,
            'action_xmlid': 'connecta_vas.action_vas_period',
        }),
        ('vas_ops_btn_loan_repay', {
            'group_id': vay_group.id,
            'zone': 'process',
            'label': 'Trả gốc',
            'icon': 'fa-money',
            'row': 1,
            'sequence': 40,
            'action_xmlid': 'connecta_vas.action_vas_loan',
        }),
        ('vas_ops_btn_loan_settle', {
            'group_id': vay_group.id,
            'zone': 'process',
            'label': 'Tất toán',
            'icon': 'fa-check-circle',
            'row': 1,
            'sequence': 50,
            'action_xmlid': 'connecta_vas.action_vas_loan',
        }),
    ]
    for xmlid, vals in vay_btns:
        _ensure_button(xmlid, vals)
    contract = env.ref('connecta_vas.vas_ops_btn_loan_contract')
    sched = env.ref('connecta_vas.vas_ops_btn_loan_schedule')
    accrue = env.ref('connecta_vas.vas_ops_btn_loan_accrue')
    repay = env.ref('connecta_vas.vas_ops_btn_loan_repay')
    settle = env.ref('connecta_vas.vas_ops_btn_loan_settle')
    contract.write({'next_ids': [(6, 0, [sched.id])]})
    sched.write({'next_ids': [(6, 0, [accrue.id])]})
    accrue.write({'next_ids': [(6, 0, [repay.id])]})
    repay.write({'next_ids': [(6, 0, [settle.id])]})

    von_btns = [
        ('vas_ops_btn_von_profit', {
            'group_id': von_group.id,
            'zone': 'process',
            'label': 'Phân phối LN / quỹ',
            'icon': 'fa-share-alt',
            'row': 1,
            'sequence': 10,
            'action_xmlid': 'connecta_vas.action_vas_profit_distribution',
        }),
        ('vas_ops_btn_von_capital', {
            'group_id': von_group.id,
            'zone': 'process',
            'label': 'Góp vốn hiện vật',
            'icon': 'fa-gift',
            'row': 1,
            'sequence': 20,
            'action_xmlid': 'connecta_vas.action_vas_capital_in_kind',
        }),
    ]
    for xmlid, vals in von_btns:
        _ensure_button(xmlid, vals)

    # Gỡ nút cũ nếu còn sót trên nhóm Vay (khi tách từ hub Vay & Vốn)
    stale = Button.search([
        ('group_id', '=', vay_group.id),
        ('id', 'not in', [contract.id, sched.id, accrue.id, repay.id, settle.id]),
    ])
    if stale:
        stale.unlink()
