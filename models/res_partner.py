import logging
from odoo import models

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def write(self, vals):
        if self.env.context.get('_skip_logo_sync'):
            return super().write(vals)

        res = super().write(vals)

        if 'image_1920' in vals:
            admin = self.env['res.users'].sudo().search([
                ('partner_id', 'in', self.ids),
                ('active', '=', True),
            ], limit=1)
            if admin:
                _logger.info(
                    'Admin partner %s image updated directly via partner write',
                    admin.id,
                )
                admin.sudo()._sync_avatar_to_branding(admin.image_1920)

        return res
