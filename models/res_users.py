import logging
from odoo import models

_logger = logging.getLogger(__name__)


class ResUsers(models.Model):
    _inherit = 'res.users'

    def write(self, vals):
        if self.env.context.get('_skip_logo_sync'):
            return super(ResUsers, self).write(vals)

        if 'image_1920' in vals:
            admin = self._get_admin_user()
            if admin and admin.id in self.ids:
                raw = vals['image_1920']
                _logger.info('Admin %s avatar updated (len=%s)', admin.id, len(raw or ''))
                result = super(ResUsers, self.with_context(_skip_logo_sync=True)).write(vals)
                self._sync_avatar_to_branding(raw)
                return result
        return super(ResUsers, self).write(vals)

    def _get_admin_user(self):
        return self.env['res.users'].sudo().search(
            [('active', '=', True)], limit=1, order='id asc',
        )

    def _sync_avatar_to_branding(self, raw):
        company = self.env['res.company'].sudo().search([], limit=1)
        if not company:
            _logger.error('No company found for branding sync')
            return

        partner = company.partner_id.sudo()
        partner.with_context(_skip_logo_sync=True).write({'image_1920': raw or False})
        _logger.info('Company logo updated for company %s', company.id)

        company._compute_logo_web()
        _logger.info('logo_web regenerated')

        partner.flush_recordset(['image_1920'])
        company.flush_recordset(['logo_web'])

        stale = self.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'res.company'),
            ('res_id', '=', company.id),
            ('res_field', 'in', ['logo', 'logo_web']),
        ])
        stale |= self.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'res.partner'),
            ('res_id', '=', partner.id),
            ('res_field', '=', 'image_1920'),
        ])
        if stale:
            stale.unlink()
            _logger.info('Deleted %d stale branding attachments', len(stale))

        company.invalidate_recordset(['logo', 'logo_web'])
        partner.invalidate_recordset(['image_1920'])
        _logger.info('Cache invalidated')
