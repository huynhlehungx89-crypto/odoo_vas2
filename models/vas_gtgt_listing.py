# -*- coding: utf-8 -*-
"""Bảng kê hóa đơn GTGT (công cụ nội bộ) + lưới đối chiếu sổ / tờ khai."""
from collections import defaultdict

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero, float_round


PURCHASE_GROUPS = [
    ('taxable_only', 'Dùng riêng hoạt động chịu thuế'),
    ('exempt_only', 'Dùng riêng hoạt động không chịu thuế'),
    ('mixed', 'Dùng chung'),
    ('investment', 'Dự án đầu tư'),
    ('unset', 'Chưa xác định mục đích'),
]

SALE_GROUPS = [
    ('26', 'Không chịu thuế GTGT'),
    ('29', 'Thuế suất 0%'),
    ('30', 'Thuế suất 5%'),
    ('32', 'Thuế suất 10%'),
    ('32a', 'Không kê khai, tính nộp thuế'),
    ('32b', 'Không tính vào giá tính thuế'),
    ('34a', 'Ngoài phạm vi PL thuế GTGT'),
]


class VasGtgtListing(models.Model):
    _name = 'vas.gtgt.listing'
    _description = 'Bảng kê hóa đơn GTGT'
    _order = 'date_start desc, listing_type, id'

    name = fields.Char(compute='_compute_name', store=True)
    company_id = fields.Many2one(
        'res.company', required=True, ondelete='cascade', index=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(related='company_id.currency_id', store=True)
    listing_type = fields.Selection(
        [('purchase', 'Mua vào'), ('sale', 'Bán ra')],
        required=True, index=True,
    )
    date_start = fields.Date(required=True, index=True)
    date_end = fields.Date(required=True, index=True)
    line_ids = fields.One2many('vas.gtgt.listing.line', 'listing_id')
    dropped_ids = fields.One2many('vas.gtgt.listing.dropped', 'listing_id')
    reconcile_ids = fields.One2many('vas.gtgt.listing.reconcile', 'listing_id')
    declaration_id = fields.Many2one(
        'vas.gtgt.declaration', string='Tờ khai đối chiếu',
        ondelete='set null',
    )

    # Năm dòng tổng mua vào
    total_purchase_value = fields.Monetary(currency_field='currency_id')
    total_import_value = fields.Monetary(currency_field='currency_id')
    total_purchase_tax = fields.Monetary(currency_field='currency_id')
    total_deductible_tax = fields.Monetary(currency_field='currency_id')
    total_import_tax = fields.Monetary(currency_field='currency_id')

    drop_warning = fields.Text(readonly=True)
    partner_vat_warning = fields.Text(readonly=True)
    import_flag_warning = fields.Text(readonly=True)
    show_purpose_groups = fields.Boolean(
        compute='_compute_show_purpose_groups',
    )

    @api.depends('listing_type', 'date_start', 'date_end', 'company_id')
    def _compute_name(self):
        for rec in self:
            kind = dict(rec._fields['listing_type'].selection).get(
                rec.listing_type, '',
            )
            rec.name = _('Bảng kê %s %s → %s') % (
                kind, rec.date_start or '', rec.date_end or '',
            )

    @api.depends('company_id', 'listing_type')
    def _compute_show_purpose_groups(self):
        for rec in self:
            rec.show_purpose_groups = bool(
                rec.listing_type == 'purchase'
                and rec.company_id.vas_has_exempt_sales
            )

    def action_rebuild(self):
        for rec in self:
            rec._rebuild()
        return True

    def action_open_dropped(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Dòng rớt khỏi bảng kê'),
            'res_model': 'vas.gtgt.listing.dropped',
            'view_mode': 'list,form',
            'domain': [('listing_id', '=', self.id)],
            'target': 'current',
        }

    def action_reconcile_ledger(self):
        self.ensure_one()
        self._rebuild_reconcile_ledger()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Đối chiếu bảng kê ↔ sổ VAS'),
            'res_model': 'vas.gtgt.listing.reconcile',
            'view_mode': 'list',
            'domain': [
                ('listing_id', '=', self.id),
                ('compare_kind', '=', 'ledger'),
            ],
        }

    def action_reconcile_declaration(self):
        self.ensure_one()
        if not self.declaration_id:
            raise UserError(_('Chọn tờ khai để đối chiếu.'))
        self._rebuild_reconcile_declaration()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Đối chiếu bảng kê ↔ tờ khai'),
            'res_model': 'vas.gtgt.listing.reconcile',
            'view_mode': 'list',
            'domain': [
                ('listing_id', '=', self.id),
                ('compare_kind', '=', 'declaration'),
            ],
        }

    def _rebuild(self):
        self.ensure_one()
        self.line_ids.unlink()
        self.dropped_ids.unlink()
        self.reconcile_ids.unlink()
        if self.listing_type == 'purchase':
            self._rebuild_purchase()
        else:
            self._rebuild_sale()

    def _period_domain_lines(self, extra=None):
        domain = [
            ('move_id.company_id', '=', self.company_id.id),
            ('move_id.state', '=', 'posted'),
            ('date', '>=', self.date_start),
            ('date', '<=', self.date_end),
        ]
        if extra:
            domain += extra
        return domain

    def _resolve_odoo_invoice(self, move):
        """Trả (invoice_or_False, meta dict). Không đọc số tiền từ HĐ."""
        if move.source_model == 'account.move' and move.source_res_id:
            inv = self.env['account.move'].browse(move.source_res_id).exists()
            if inv:
                return inv, {
                    'number': inv.name if inv.name and inv.name != '/' else (inv.ref or ''),
                    'date': inv.invoice_date,
                    'partner': inv.partner_id,
                    'anchored': True,
                    'is_import': False,
                }
        if move.source_model == 'vas.import.vat' and move.source_res_id:
            decl = self.env['vas.import.vat'].browse(move.source_res_id).exists()
            if decl:
                return False, {
                    'number': decl.declaration_number or decl.name or '',
                    'date': decl.date,
                    'partner': decl.partner_id,
                    'anchored': True,
                    'is_import': True,
                    'import_id': decl.id,
                }
        if move.move_kind == 'import_vat':
            return False, {
                'number': move.source_ref or move.ref or move.name or '',
                'date': move.date,
                'partner': move.line_ids[:1].partner_id,
                'anchored': True,
                'is_import': True,
            }
        return False, {
            'number': '',
            'date': False,
            'partner': move.line_ids[:1].partner_id,
            'anchored': False,
            'is_import': False,
        }

    def _rebuild_purchase(self):
        Line = self.env['vas.move.line']
        tax_lines = Line.search(self._period_domain_lines([
            ('debit', '>', 0),
            ('account_id.code', '=like', '1331%'),
            '|', '|',
            ('tax_id', '!=', False),
            ('move_id.source_model', '=', 'vas.import.vat'),
            ('move_id.move_kind', '=', 'import_vat'),
        ]))
        show_multi = self.company_id.vas_has_exempt_sales
        buckets = defaultdict(lambda: {
            'untaxed': 0.0, 'tax': 0.0, 'deductible': 0.0,
            'lines': Line, 'meta': None, 'purpose': 'taxable_only',
            'is_import': False, 'note': '',
        })
        unanchored = []
        dropped = []
        missing_vat_notes = []
        import_ids = set()

        for tl in tax_lines:
            move = tl.move_id
            inv, meta = self._resolve_odoo_invoice(move)
            missing = []
            if not meta['anchored']:
                # Phiếu chi / số dư / bút toán tay — nhóm riêng, không rớt
                unanchored.append(tl)
                continue
            if not meta['number']:
                missing.append('số hóa đơn')
            if not meta['date']:
                missing.append('ngày')
            if not tl.tax_id and not meta['is_import']:
                missing.append('thuế suất')
            if missing:
                dropped.append((tl, missing, meta))
                continue

            purpose = tl.use_purpose or 'unset'
            if not show_multi:
                purpose = 'taxable_only'
            key = (
                purpose,
                move.source_model or '',
                move.source_res_id or 0,
                meta['is_import'],
            )
            b = buckets[key]
            b['untaxed'] += tl.deduction_base_untaxed or 0.0
            b['tax'] += tl.debit
            b['deductible'] += tl.deductible_amount or 0.0
            b['lines'] |= tl
            b['meta'] = meta
            b['purpose'] = purpose
            b['is_import'] = bool(meta['is_import'])
            if meta.get('import_id'):
                import_ids.add(meta['import_id'])
            partner = meta['partner']
            if partner and not partner.vat:
                missing_vat_notes.append(
                    _('%s (HĐ %s)') % (partner.display_name, meta['number'])
                )

        # Customs declarations in period (for flag warning)
        customs = self.env['vas.import.vat'].search([
            ('company_id', '=', self.company_id.id),
            ('date', '>=', self.date_start),
            ('date', '<=', self.date_end),
            ('state', 'in', ('confirmed', 'paid')),
        ])

        seq = 10
        create_lines = []
        group_order = [g[0] for g in PURCHASE_GROUPS]
        if not show_multi:
            group_order = ['taxable_only']

        tot_v = tot_iv = tot_t = tot_d = tot_it = 0.0
        for gcode in group_order:
            gname = dict(PURCHASE_GROUPS).get(gcode, gcode)
            g_untaxed = g_tax = g_ded = 0.0
            for key, b in sorted(buckets.items(), key=lambda x: x[0]):
                if b['purpose'] != gcode:
                    continue
                meta = b['meta']
                partner = meta['partner']
                create_lines.append({
                    'listing_id': self.id,
                    'sequence': seq,
                    'line_kind': 'detail',
                    'group_code': gcode,
                    'group_label': gname,
                    'invoice_number': meta['number'],
                    'invoice_date': meta['date'],
                    'partner_name': partner.display_name if partner else '',
                    'partner_vat': partner.vat if partner else '',
                    'amount_untaxed': float_round(b['untaxed'], 0),
                    'amount_tax': float_round(b['tax'], 0),
                    'amount_deductible': float_round(b['deductible'], 0),
                    'is_import': b['is_import'],
                    'source_model': key[1] or False,
                    'source_res_id': key[2] or False,
                    'note': b['note'],
                })
                seq += 1
                g_untaxed += b['untaxed']
                g_tax += b['tax']
                g_ded += b['deductible']
                tot_v += b['untaxed']
                tot_t += b['tax']
                tot_d += b['deductible']
                if b['is_import']:
                    tot_iv += b['untaxed']
                    tot_it += b['tax']
            if show_multi or gcode == 'taxable_only':
                create_lines.append({
                    'listing_id': self.id,
                    'sequence': seq,
                    'line_kind': 'group_total',
                    'group_code': gcode,
                    'group_label': _('Cộng nhóm: %s') % gname,
                    'amount_untaxed': float_round(g_untaxed, 0),
                    'amount_tax': float_round(g_tax, 0),
                    'amount_deductible': float_round(g_ded, 0),
                })
                seq += 1

        # Unanchored group
        if unanchored:
            u_tax = sum(l.debit for l in unanchored)
            u_base = sum(l.deduction_base_untaxed or 0.0 for l in unanchored)
            u_ded = sum(l.deductible_amount or 0.0 for l in unanchored)
            for tl in unanchored:
                create_lines.append({
                    'listing_id': self.id,
                    'sequence': seq,
                    'line_kind': 'unanchored',
                    'group_code': 'unanchored',
                    'group_label': _('Thuế không neo hóa đơn'),
                    'invoice_number': tl.move_id.ref or tl.move_id.name or '',
                    'invoice_date': tl.date,
                    'partner_name': tl.partner_id.display_name if tl.partner_id else '',
                    'partner_vat': tl.partner_id.vat if tl.partner_id else '',
                    'amount_untaxed': float_round(tl.deduction_base_untaxed or 0.0, 0),
                    'amount_tax': float_round(tl.debit, 0),
                    'amount_deductible': float_round(tl.deductible_amount or 0.0, 0),
                    'source_model': tl.move_id.source_model or False,
                    'source_res_id': tl.move_id.source_res_id or False,
                    'note': _('Nguồn: %s / %s') % (
                        tl.move_id.move_kind, tl.move_id.source_model or '—',
                    ),
                })
                seq += 1
            create_lines.append({
                'listing_id': self.id,
                'sequence': seq,
                'line_kind': 'group_total',
                'group_code': 'unanchored',
                'group_label': _('Cộng: thuế không neo hóa đơn'),
                'amount_untaxed': float_round(u_base, 0),
                'amount_tax': float_round(u_tax, 0),
                'amount_deductible': float_round(u_ded, 0),
            })
            seq += 1
            tot_v += u_base
            tot_t += u_tax
            tot_d += u_ded

        self.env['vas.gtgt.listing.line'].create(create_lines)

        drop_recs = []
        drop_tax = 0.0
        reasons_count = defaultdict(int)
        for tl, missing, meta in dropped:
            drop_tax += tl.debit
            for r in missing:
                reasons_count[r] += 1
            drop_recs.append({
                'listing_id': self.id,
                'move_line_id': tl.id,
                'missing_reasons': ', '.join(missing),
                'amount_tax': tl.debit,
                'move_ref': tl.move_id.display_name,
                'source_hint': '%s,%s' % (
                    tl.move_id.source_model or '', tl.move_id.source_res_id or '',
                ),
            })
        self.env['vas.gtgt.listing.dropped'].create(drop_recs)

        drop_warn = False
        if dropped:
            drop_warn = _(
                '%(n)s dòng rớt khỏi bảng kê (thiếu: %(why)s). '
                'Tổng tiền thuế %(tax)s. Bấm «Dòng rớt» để xem danh sách.',
                n=len(dropped),
                why=', '.join('%s×%s' % (k, v) for k, v in reasons_count.items()),
                tax=int(drop_tax),
            )
        vat_warn = False
        if missing_vat_notes:
            vat_warn = _(
                '%(n)s dòng thiếu MST đối tác (vẫn lên bảng kê): %(list)s',
                n=len(missing_vat_notes),
                list='; '.join(missing_vat_notes[:20]),
            )
        flagged = len(self.line_ids.filtered(
            lambda l: l.line_kind == 'detail' and l.is_import
        ))
        imp_warn = False
        if flagged != len(customs):
            imp_warn = _(
                'Cảnh báo: %(f)s dòng tích nhập khẩu ≠ %(c)s chứng từ hải quan trong kỳ.',
                f=flagged, c=len(customs),
            )

        self.write({
            'total_purchase_value': float_round(tot_v, 0),
            'total_import_value': float_round(tot_iv, 0),
            'total_purchase_tax': float_round(tot_t, 0),
            'total_deductible_tax': float_round(tot_d, 0),
            'total_import_tax': float_round(tot_it, 0),
            'drop_warning': drop_warn,
            'partner_vat_warning': vat_warn,
            'import_flag_warning': imp_warn,
        })

    def _rebuild_sale(self):
        Line = self.env['vas.move.line']
        value_lines = Line.search(self._period_domain_lines([
            ('credit', '>', 0),
            ('account_id.code', '=like', '511%'),
        ]))
        tax_lines = Line.search(self._period_domain_lines([
            ('credit', '>', 0),
            ('account_id.code', '=like', '3331%'),
            ('tax_id', '!=', False),
        ]))

        # Key by (source, tag)
        buckets = defaultdict(lambda: {
            'untaxed': 0.0, 'tax': 0.0, 'meta': None, 'tag': '',
            'lines': Line,
        })
        unanchored = []
        dropped = []
        missing_vat_notes = []

        def _tag_of(tax):
            if not tax:
                return ''
            return tax.declaration_value_tag or ''

        # Value lines first
        for vl in value_lines:
            move = vl.move_id
            inv, meta = self._resolve_odoo_invoice(move)
            tag = _tag_of(vl.tax_id)
            if not meta['anchored']:
                if vl.tax_id or (vl.account_id.code or '').startswith('511'):
                    # doanh thu không neo — hiếm; gom unanchored nếu có tax_id
                    if vl.tax_id:
                        unanchored.append(('value', vl))
                continue
            missing = []
            if not meta['number']:
                missing.append('số hóa đơn')
            if not meta['date']:
                missing.append('ngày')
            if not vl.tax_id and not tag:
                # empty tax on 511 with empty_line match may still be exempt
                if vl.tax_status == 'undetermined':
                    missing.append('thuế suất')
            if missing:
                dropped.append((vl, missing, meta))
                continue
            if not tag:
                # dòng 511 không thuế → coi như không chịu (26) nếu empty
                tag = '26'
            key = (tag, move.source_model or '', move.source_res_id or 0)
            b = buckets[key]
            b['untaxed'] += vl.credit
            b['meta'] = meta
            b['tag'] = tag
            b['lines'] |= vl
            partner = meta['partner']
            if partner and not partner.vat:
                missing_vat_notes.append(
                    _('%s (HĐ %s)') % (partner.display_name, meta['number'])
                )

        for tl in tax_lines:
            move = tl.move_id
            inv, meta = self._resolve_odoo_invoice(move)
            tag = tl.tax_id.declaration_tax_tag or tl.tax_id.declaration_value_tag or ''
            # Map tax tags 31→30 group, 33→32 group for display grouping by rate family
            value_tag = tl.tax_id.declaration_value_tag or tag
            if not meta['anchored']:
                unanchored.append(('tax', tl))
                continue
            missing = []
            if not meta['number']:
                missing.append('số hóa đơn')
            if not meta['date']:
                missing.append('ngày')
            if not tl.tax_id:
                missing.append('thuế suất')
            if missing:
                dropped.append((tl, missing, meta))
                continue
            key = (value_tag, move.source_model or '', move.source_res_id or 0)
            b = buckets[key]
            b['tax'] += tl.credit
            if not b['meta']:
                b['meta'] = meta
            b['tag'] = value_tag
            b['lines'] |= tl

        seq = 10
        create_lines = []
        for gcode, gname in SALE_GROUPS:
            g_u = g_t = 0.0
            for key, b in sorted(buckets.items()):
                if b['tag'] != gcode:
                    continue
                meta = b['meta'] or {}
                partner = meta.get('partner')
                create_lines.append({
                    'listing_id': self.id,
                    'sequence': seq,
                    'line_kind': 'detail',
                    'group_code': gcode,
                    'group_label': gname,
                    'invoice_number': meta.get('number') or '',
                    'invoice_date': meta.get('date') or False,
                    'partner_name': partner.display_name if partner else '',
                    'partner_vat': partner.vat if partner else '',
                    'amount_untaxed': float_round(b['untaxed'], 0),
                    'amount_tax': float_round(b['tax'], 0),
                    'source_model': key[1] or False,
                    'source_res_id': key[2] or False,
                })
                seq += 1
                g_u += b['untaxed']
                g_t += b['tax']
            create_lines.append({
                'listing_id': self.id,
                'sequence': seq,
                'line_kind': 'group_total',
                'group_code': gcode,
                'group_label': _('Cộng nhóm: %s') % gname,
                'amount_untaxed': float_round(g_u, 0),
                'amount_tax': float_round(g_t, 0),
            })
            seq += 1

        if unanchored:
            for kind, tl in unanchored:
                amt_u = tl.credit if kind == 'value' else 0.0
                amt_t = tl.credit if kind == 'tax' else 0.0
                create_lines.append({
                    'listing_id': self.id,
                    'sequence': seq,
                    'line_kind': 'unanchored',
                    'group_code': 'unanchored',
                    'group_label': _('Thuế/DT không neo hóa đơn'),
                    'invoice_number': tl.move_id.ref or tl.move_id.name or '',
                    'invoice_date': tl.date,
                    'amount_untaxed': float_round(amt_u, 0),
                    'amount_tax': float_round(amt_t, 0),
                    'source_model': tl.move_id.source_model or False,
                    'source_res_id': tl.move_id.source_res_id or False,
                    'note': _('Nguồn: %s') % (tl.move_id.move_kind,),
                })
                seq += 1

        self.env['vas.gtgt.listing.line'].create(create_lines)

        drop_recs = []
        drop_tax = 0.0
        reasons_count = defaultdict(int)
        for tl, missing, meta in dropped:
            tax_amt = tl.credit if (tl.account_id.code or '').startswith('333') else 0.0
            drop_tax += tax_amt
            for r in missing:
                reasons_count[r] += 1
            drop_recs.append({
                'listing_id': self.id,
                'move_line_id': tl.id,
                'missing_reasons': ', '.join(missing),
                'amount_tax': tax_amt,
                'move_ref': tl.move_id.display_name,
            })
        self.env['vas.gtgt.listing.dropped'].create(drop_recs)
        drop_warn = False
        if dropped:
            drop_warn = _(
                '%(n)s dòng rớt khỏi bảng kê (thiếu: %(why)s). Tổng thuế %(tax)s.',
                n=len(dropped),
                why=', '.join('%s×%s' % (k, v) for k, v in reasons_count.items()),
                tax=int(drop_tax),
            )
        vat_warn = False
        if missing_vat_notes:
            vat_warn = _(
                '%(n)s dòng thiếu MST đối tác (vẫn lên bảng kê).',
                n=len(set(missing_vat_notes)),
            )
        self.write({
            'drop_warning': drop_warn,
            'partner_vat_warning': vat_warn,
            'import_flag_warning': False,
            'total_purchase_value': 0.0,
            'total_import_value': 0.0,
            'total_purchase_tax': 0.0,
            'total_deductible_tax': 0.0,
            'total_import_tax': 0.0,
        })

    def _group_total(self, group_code, field='amount_tax'):
        lines = self.line_ids.filtered(
            lambda l: l.group_code == group_code and l.line_kind == 'group_total'
        )
        return sum(lines.mapped(field))

    def _listing_qualifies_purchase_line(self, tl):
        """Cùng quy tắc với bảng kê: neo được + đủ số/ngày (+thuế nếu không NK)."""
        _inv, meta = self._resolve_odoo_invoice(tl.move_id)
        if not meta['anchored']:
            return 'unanchored', meta
        if not meta['number'] or not meta['date']:
            return 'dropped', meta
        if not tl.tax_id and not meta['is_import']:
            return 'dropped', meta
        purpose = tl.use_purpose or 'unset'
        if not self.company_id.vas_has_exempt_sales:
            purpose = 'taxable_only'
        return purpose, meta

    def _listing_qualifies_sale_value_line(self, vl):
        _inv, meta = self._resolve_odoo_invoice(vl.move_id)
        if not meta['anchored']:
            return 'unanchored', meta, ''
        if not meta['number'] or not meta['date']:
            return 'dropped', meta, ''
        tag = (vl.tax_id.declaration_value_tag if vl.tax_id else '') or '26'
        if not vl.tax_id and vl.tax_status == 'undetermined':
            return 'dropped', meta, ''
        return tag, meta, tag

    def _rebuild_reconcile_ledger(self):
        """Đối chiếu nhóm bảng kê ↔ phát sinh sổ (cùng tập dòng đủ điều kiện lên BK)."""
        self.ensure_one()
        self.reconcile_ids.filtered(lambda r: r.compare_kind == 'ledger').unlink()
        Line = self.env['vas.move.line']
        rows = []
        if self.listing_type == 'purchase':
            list_tax = sum(self.line_ids.filtered(
                lambda l: l.line_kind in ('detail', 'unanchored')
            ).mapped('amount_tax'))
            ledger_tax = 0.0
            by_group = defaultdict(float)
            for tl in Line.search(self._period_domain_lines([
                ('debit', '>', 0),
                ('account_id.code', '=like', '1331%'),
                '|', '|',
                ('tax_id', '!=', False),
                ('move_id.source_model', '=', 'vas.import.vat'),
                ('move_id.move_kind', '=', 'import_vat'),
            ])):
                status, _meta = self._listing_qualifies_purchase_line(tl)
                if status == 'dropped':
                    continue
                ledger_tax += tl.debit
                by_group[status] += tl.debit
            rows.append({
                'listing_id': self.id,
                'compare_kind': 'ledger',
                'code': '1331',
                'name': _('Tổng thuế mua vào (1331 · đủ điều kiện BK)'),
                'amount_listing': float_round(list_tax, 0),
                'amount_other': float_round(ledger_tax, 0),
            })
            show_multi = self.company_id.vas_has_exempt_sales
            groups = [g[0] for g in PURCHASE_GROUPS] if show_multi else ['taxable_only']
            groups.append('unanchored')
            labels = dict(PURCHASE_GROUPS + [('unanchored', _('Không neo'))])
            for gcode in groups:
                list_amt = sum(self.line_ids.filtered(
                    lambda l, c=gcode: l.group_code == c and l.line_kind in (
                        'detail', 'unanchored',
                    )
                ).mapped('amount_tax'))
                rows.append({
                    'listing_id': self.id,
                    'compare_kind': 'ledger',
                    'code': gcode,
                    'name': labels.get(gcode, gcode),
                    'amount_listing': float_round(list_amt, 0),
                    'amount_other': float_round(by_group.get(gcode, 0.0), 0),
                })
        else:
            # Gom sổ theo cùng quy tắc neo/số/ngày như bảng kê
            ledger_u = defaultdict(float)
            ledger_t = defaultdict(float)
            for vl in Line.search(self._period_domain_lines([
                ('credit', '>', 0),
                ('account_id.code', '=like', '511%'),
            ])):
                status, _meta, tag = self._listing_qualifies_sale_value_line(vl)
                if status in ('dropped', 'unanchored'):
                    continue
                ledger_u[status] += vl.credit
            for tl in Line.search(self._period_domain_lines([
                ('credit', '>', 0),
                ('account_id.code', '=like', '3331%'),
                ('tax_id', '!=', False),
            ])):
                _inv, meta = self._resolve_odoo_invoice(tl.move_id)
                if not meta['anchored'] or not meta['number'] or not meta['date']:
                    continue
                vtag = tl.tax_id.declaration_value_tag or ''
                if vtag:
                    ledger_t[vtag] += tl.credit
            for gcode, gname in SALE_GROUPS:
                list_u = sum(self.line_ids.filtered(
                    lambda l, c=gcode: l.group_code == c and l.line_kind == 'detail'
                ).mapped('amount_untaxed'))
                list_t = sum(self.line_ids.filtered(
                    lambda l, c=gcode: l.group_code == c and l.line_kind == 'detail'
                ).mapped('amount_tax'))
                rows.append({
                    'listing_id': self.id,
                    'compare_kind': 'ledger',
                    'code': gcode + '_value',
                    'name': _('%s — giá trị') % gname,
                    'amount_listing': float_round(list_u, 0),
                    'amount_other': float_round(ledger_u.get(gcode, 0.0), 0),
                })
                if gcode in ('30', '32'):
                    rows.append({
                        'listing_id': self.id,
                        'compare_kind': 'ledger',
                        'code': gcode + '_tax',
                        'name': _('%s — thuế') % gname,
                        'amount_listing': float_round(list_t, 0),
                        'amount_other': float_round(ledger_t.get(gcode, 0.0), 0),
                    })
        for r in rows:
            r['difference'] = float_round(
                r['amount_listing'] - r['amount_other'], 0,
            )
        self.env['vas.gtgt.listing.reconcile'].create(rows)

    def _rebuild_reconcile_declaration(self):
        self.ensure_one()
        decl = self.declaration_id
        if not decl:
            return
        self.reconcile_ids.filtered(lambda r: r.compare_kind == 'declaration').unlink()
        amt = {l.code: l.amount for l in decl.line_ids}
        rows = []
        if self.listing_type == 'purchase':
            mapping = [
                ('23', 'total_purchase_value', _(' [23] Giá trị mua vào')),
                ('23a', 'total_import_value', _(' [23a] Giá trị NK')),
                ('24', 'total_purchase_tax', _(' [24] Thuế mua vào')),
                ('24a', 'total_import_tax', _(' [24a] Thuế NK')),
                ('25', 'total_deductible_tax', _(' [25] Thuế được khấu trừ')),
            ]
            for code, field, label in mapping:
                list_amt = self[field]
                rows.append({
                    'listing_id': self.id,
                    'compare_kind': 'declaration',
                    'code': code,
                    'name': label,
                    'amount_listing': float_round(list_amt, 0),
                    'amount_other': float_round(amt.get(code, 0.0), 0),
                    'difference': float_round(list_amt - amt.get(code, 0.0), 0),
                })
        else:
            # sale indicators from group totals
            tag_map = [
                ('26', '26', 'amount_untaxed'),
                ('29', '29', 'amount_untaxed'),
                ('30', '30', 'amount_untaxed'),
                ('31', '30', 'amount_tax'),
                ('32', '32', 'amount_untaxed'),
                ('32a', '32a', 'amount_untaxed'),
                ('32b', '32b', 'amount_untaxed'),
                ('33', '32', 'amount_tax'),
                ('34a', '34a', 'amount_untaxed'),
            ]
            for code, gcode, field in tag_map:
                list_amt = sum(self.line_ids.filtered(
                    lambda l, g=gcode: l.group_code == g and l.line_kind == 'detail'
                ).mapped(field))
                rows.append({
                    'listing_id': self.id,
                    'compare_kind': 'declaration',
                    'code': code,
                    'name': _('Chỉ tiêu [%s]') % code,
                    'amount_listing': float_round(list_amt, 0),
                    'amount_other': float_round(amt.get(code, 0.0), 0),
                    'difference': float_round(list_amt - amt.get(code, 0.0), 0),
                })
            # [34] theo công thức tờ khai: [26]+[27]+[34a], [27]=[29]+[30]+[32]+[32a]-[32b]
            def _g(code, field='amount_untaxed'):
                return sum(self.line_ids.filtered(
                    lambda l, c=code: l.group_code == c and l.line_kind == 'detail'
                ).mapped(field))

            list_34 = (
                _g('26') + _g('29') + _g('30') + _g('32') + _g('32a')
                - _g('32b') + _g('34a')
            )
            list_35 = _g('30', 'amount_tax') + _g('32', 'amount_tax')
            for code, list_amt in (('34', list_34), ('35', list_35)):
                rows.append({
                    'listing_id': self.id,
                    'compare_kind': 'declaration',
                    'code': code,
                    'name': _('Chỉ tiêu [%s]') % code,
                    'amount_listing': float_round(list_amt, 0),
                    'amount_other': float_round(amt.get(code, 0.0), 0),
                    'difference': float_round(list_amt - amt.get(code, 0.0), 0),
                })
        self.env['vas.gtgt.listing.reconcile'].create(rows)


class VasGtgtListingLine(models.Model):
    _name = 'vas.gtgt.listing.line'
    _description = 'Dòng bảng kê GTGT'
    _order = 'sequence, id'

    listing_id = fields.Many2one(
        'vas.gtgt.listing', required=True, ondelete='cascade', index=True,
    )
    sequence = fields.Integer(default=10)
    line_kind = fields.Selection(
        [
            ('detail', 'Chi tiết'),
            ('group_total', 'Cộng nhóm'),
            ('unanchored', 'Không neo HĐ'),
        ],
        required=True, default='detail', index=True,
    )
    group_code = fields.Char(index=True)
    group_label = fields.Char()
    invoice_number = fields.Char(string='Số hóa đơn')
    invoice_date = fields.Date(string='Ngày')
    partner_name = fields.Char()
    partner_vat = fields.Char(string='MST')
    amount_untaxed = fields.Monetary(currency_field='currency_id')
    amount_tax = fields.Monetary(currency_field='currency_id')
    amount_deductible = fields.Monetary(currency_field='currency_id')
    is_import = fields.Boolean(string='Nhập khẩu')
    note = fields.Char()
    source_model = fields.Char()
    source_res_id = fields.Integer()
    currency_id = fields.Many2one(related='listing_id.currency_id')

    def action_open_source(self):
        self.ensure_one()
        if not self.source_model or not self.source_res_id:
            raise UserError(_('Không có chứng từ gốc để mở.'))
        if self.source_model not in self.env:
            raise UserError(_('Model nguồn không tồn tại: %s') % self.source_model)
        return {
            'type': 'ir.actions.act_window',
            'res_model': self.source_model,
            'res_id': self.source_res_id,
            'view_mode': 'form',
            'target': 'current',
        }


class VasGtgtListingDropped(models.Model):
    _name = 'vas.gtgt.listing.dropped'
    _description = 'Dòng rớt khỏi bảng kê GTGT'
    _order = 'id'

    listing_id = fields.Many2one(
        'vas.gtgt.listing', required=True, ondelete='cascade', index=True,
    )
    move_line_id = fields.Many2one('vas.move.line', ondelete='set null')
    missing_reasons = fields.Char(required=True)
    amount_tax = fields.Monetary(currency_field='currency_id')
    move_ref = fields.Char()
    source_hint = fields.Char()
    currency_id = fields.Many2one(related='listing_id.currency_id')


class VasGtgtListingReconcile(models.Model):
    _name = 'vas.gtgt.listing.reconcile'
    _description = 'Đối chiếu bảng kê GTGT'
    _order = 'compare_kind, code, id'

    listing_id = fields.Many2one(
        'vas.gtgt.listing', required=True, ondelete='cascade', index=True,
    )
    compare_kind = fields.Selection(
        [('ledger', 'Với sổ VAS'), ('declaration', 'Với tờ khai')],
        required=True, index=True,
    )
    code = fields.Char(required=True)
    name = fields.Char(required=True)
    amount_listing = fields.Monetary(currency_field='currency_id')
    amount_other = fields.Monetary(
        string='Số đối chiếu', currency_field='currency_id',
    )
    difference = fields.Monetary(currency_field='currency_id')
    currency_id = fields.Many2one(related='listing_id.currency_id')
    is_mismatch = fields.Boolean(compute='_compute_is_mismatch')

    @api.depends('difference')
    def _compute_is_mismatch(self):
        for rec in self:
            rec.is_mismatch = float_compare(
                abs(rec.difference), 0.5, precision_digits=0,
            ) > 0
