# Content Screening Admin Settings Fix

## Issue

Content Screening was difficult to find in Admin Settings, and enabling it in V2 could appear to succeed without changing the persisted setting.

**Fixed in version: 0.261.107**, recorded in `application\single_app\config.py`.

**Related issue:** [#1476](https://github.com/microsoft/simplechat/issues/1476).

## Root cause

The V2 field used `depends_on` for Enhanced Citations, which hid the switch instead of explaining the prerequisite. It was grouped inside Content Safety even though those capabilities are independent. The rule/model fields and API helpers existed, but no policy-editing controller mounted them in the live interface.

The generic V2 settings PATCH handler also ignored `update_settings()` returning `False`. It returned a success-shaped response with the requested value even when storage or screening validation rejected the update. Without a way to save an active baseline, a first-time screening activation was especially likely to fail.

## Changes

Content Screening now has its own tab under **Security** in both interfaces. The switch remains visible when Enhanced Citations is disabled, with a prerequisite notice and a link to configure it. Policy preparation remains available before enrollment is enabled.

The V2 editor uses the existing authorized load, save, and sample-test APIs. It preserves policy ETags, reloads after conflicts, uses server-provided starter rules and criteria, and offers only configured/approved model references. Workspace additions cannot submit global model permissions. Clearing an optional model uses the backend's empty-reference shape.

The V2 settings handler checks persistence before reporting success. Missing baseline or citation prerequisites produce safe field-level errors; a failed write leaves the draft visible and does not report a stored value.

The root Docker context now includes `application\v2_ui` source required by the existing multistage Dockerfile, while still excluding local dependencies, built assets, tests, and secrets.

## Validation and impact

`functional_tests\test_content_screening_admin_settings_fix.py` executes the actual V2 PATCH handler with isolated storage, covers failure responses and independent Content Safety/Screening behavior, and verifies the real navigation/schema.

`ui_tests\test_v2_content_screening.py` exercises the production SPA with the shipped field declaration: discovery before citations are enabled, policy edit/save/reload, configured-model selection, sample inspection, workspace restrictions, ETag conflicts, failed settings writes, and activation with Content Safety disabled. Existing classic, schema, and template-composition coverage remains applicable.

No screening hold, reviewer authorization, or required storage/model check is weakened. The fix makes configuration accessible and rejected saves truthful.
