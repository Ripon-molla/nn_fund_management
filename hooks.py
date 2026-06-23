import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    _logger.info('=== post_init_hook START ===')

    admin = env['res.users'].sudo().search(
        [('active', '=', True)], limit=1, order='id asc',
    )
    if not admin:
        _logger.error('post_init_hook: no admin user found')
        return

    company = env['res.company'].sudo().search([], limit=1)
    if not company:
        _logger.error('post_init_hook: no company found')
        return

    avatar = admin.image_1920
    _logger.info(
        'Admin avatar: present=%s len=%s', bool(avatar), len(avatar) if avatar else 0,
    )

    partner = company.partner_id.sudo()
    partner.with_context(_skip_logo_sync=True).write({'image_1920': avatar or False})
    _logger.info('Company logo updated from admin avatar')

    company._compute_logo_web()
    _logger.info('logo_web regenerated')

    partner.flush_recordset(['image_1920'])
    company.flush_recordset(['logo_web'])

    env.registry.clear_cache('assets')
    _logger.info('Asset cache cleared')

    stale = env['ir.attachment'].sudo().search([
        ('res_model', '=', 'res.company'),
        ('res_id', '=', company.id),
        ('res_field', 'in', ['logo', 'logo_web']),
    ])
    stale |= env['ir.attachment'].sudo().search([
        ('res_model', '=', 'res.partner'),
        ('res_id', '=', partner.id),
        ('res_field', '=', 'image_1920'),
    ])
    if stale:
        stale.unlink()
        _logger.info('Deleted %d stale branding attachments', len(stale))

    company.invalidate_recordset(['logo', 'logo_web'])
    partner.invalidate_recordset(['image_1920'])
    _logger.info('ORM caches invalidated')

    _fix_company_name(env, company)
    _logger.info('=== post_init_hook END ===')


def _fix_company_name(env, company):
    """Replace stale ``'YourCompany'`` references in partner data with the
    actual company name.

    Odoo's default demo data writes the company name into each user's partner
    ``company_name`` field at creation time — but that field is a plain
    ``Char`` snapshot, so renaming the company later leaves those partners
    stuck with the old value.

    This function also corrects the stored computed fields
    ``commercial_company_name`` and ``complete_name`` when the ORM did not
    propagate their recomputation after the company partner ``name`` change.
    """
    company_name = company.name
    company_partner = company.partner_id.sudo()
    _logger.info('Fixing company name references → "%s"', company_name)

    Partner = env['res.partner'].sudo()

    # -- 1. Snapshot ``company_name`` field --------------------------------
    stale = Partner.search([('company_name', '=', 'YourCompany')])
    for rec in stale:
        rec.company_name = rec.company_id.name if rec.company_id else False
    if stale:
        _logger.info('  Fixed company_name on %d partner(s)', len(stale))

    # -- 2. Stored computed fields -----------------------------------------
    #      The company partner itself and every contact with a stale
    #      ``commercial_company_name`` / ``complete_name``.

    def _ok(val):
        """Return *val* unchanged, or the company name if *val* is
        ``'YourCompany'``."""
        return company_name if val == 'YourCompany' else val

    def _fix_stored(partner):
        """Write the correct ``commercial_company_name`` and ``complete_name``
        to *partner* (a single record)."""
        vals = {}
        n = partner.name or ''
        # ``commercial_company_name``
        if partner.is_company:
            raw_ccn = partner.name
        else:
            raw_ccn = partner.company_name or partner.sudo().commercial_partner_id.name or ''
        ccn = _ok(raw_ccn)
        if ccn != partner.commercial_company_name:
            vals['commercial_company_name'] = ccn
        # ``complete_name``
        raw_cn = n
        if (partner.company_name or partner.parent_id) and not partner.is_company:
            raw_cn = f'{ccn}, {n}'
        cn = _ok(raw_cn)
        if cn != partner.complete_name:
            vals['complete_name'] = cn
        if vals:
            partner.write(vals)

    # Address the company partner itself (is_company → name drives both).
    _fix_stored(company_partner)

    # Contacts attached via parent_id or commercial_partner_id.
    linked = Partner.search([
        '|',
        ('parent_id', '=', company_partner.id),
        ('commercial_partner_id', '=', company_partner.id),
    ])
    linked -= company_partner  # already handled above
    for rec in linked:
        _fix_stored(rec)
    if linked:
        _logger.info('  Fixed stored fields on %d partner(s)', len(linked))

    _logger.info('Company name references fixed')
