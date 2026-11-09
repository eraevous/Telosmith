# Append validation safety

Local security remediation: validation used a predictable sibling path, overwrote any existing file or symlink target, and deleted the sibling even on failure. Dry-run took this path too.

Choice: eliminate scratch writes. Store.load delegates to the same in-memory parser used by build. Build reads the original UTF-8 bytes once and validates the combined text without normalizing line endings; source anchors still use the explicit repository SourceContext. No locking, CLI changes, record rewrites, or authority changes are included.

Tests were written first: nine tests produced five failures on main (file, symlink, dry-run, parse failure, write prohibition) and four passing decoys. Existing adoption tests cover anchored appends, aliases, prefix anchors, duplicate refusal and missing final newlines. Full validation outcomes are in the accompanying local report. This is structural regression evidence, not owner acceptance or comparative value evidence. No Spec Kit workflow was run for this narrow bug fix.
