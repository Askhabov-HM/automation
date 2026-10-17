---
name: pdf-documents
description: Generate PDFs from text or structured content using a self-contained Economy or Technical layout. Default to Economy; use Technical only when explicitly requested. Includes rendering, validation, cached resources and comparison with approved versions.
---

# PDF Documents

This directory is the complete skill package. Resolve all scripts and resources relative to this `SKILL.md`, never to an `automation` checkout or another skill. Read [README.md](README.md) for the content schema, setup and advanced commands.

## Mode selection

- **Default: Economy** (`--mode economy`, also the CLI default). Black text on white portrait A4. No photos or charts; retain captions, chart data and table rows as text.
- **Technical** (`--mode technical`): use only if the user explicitly asks for Technical / the technical layout. Include requested photos, vector charts, links and tables with repeated headers.
- Agreement on text, a request for a PDF, or a general request to make it attractive does not switch the default to Technical.
- If the user explicitly asks for both formats, build both from the same content in separate calls and deliver both.
- Reuse `templates/economy/` and `templates/technical/`. The selected visual references are `references/00-economy-text.pdf` and `references/05-technical.pdf`. Do not impose their page counts or invent data.

## Generate

1. Set `SKILL_DIR` to this package's actual absolute directory. Create requested content as UTF-8 JSON or the documented simple Markdown subset. Personal inputs can live in `SKILL_DIR/inputs/` or a user-selected working directory. Keep reusable examples synthetic.
2. If the isolated runtime is missing or the command reports a dependency mismatch, run `python "SKILL_DIR/scripts/pdf_tool.py" setup --renderer pdfium`. This installs the pinned dependencies into this package; bundled fonts avoid dependence on fonts from another computer. Installed Poppler is also supported.
3. Run `python "SKILL_DIR/scripts/pdf_tool.py" build "CONTENT_PATH" --name DOCUMENT_ID` for Economy. Add `--mode technical` only when requested. Use absolute paths when running from another directory.
4. The command returns one JSON object. `files` paths are relative to `SKILL_DIR`; resolve them before opening or delivering files. Results, logs and baselines belong to this installed package, not to its source Git checkout.
5. Read the short JSON first. Open the referenced local log only if needed. Do not rewrite the generator or repeat long logs in chat.

## Verify and review

- The pipeline validates the whole PDF and renders every page. First builds and changed layout/fonts/render settings require full visual review. Otherwise inspect the listed changed pages; use full-size PNGs for dense tables and suspected clipping.
- Check substantive data as well as appearance. A pixel difference locates a change; it does not determine whether the content is correct.
- Keep `baselines/` separate from disposable `.cache/`. Do not update a baseline automatically after a build or solely because automatic checks passed.
- After the user explicitly approves the specific reviewed build, run `approve` with its exact `run_id` and actual reviewed pages. Acknowledge removed pages when required. Never claim the user approved a build based on the agent's own inspection.
- Existing approved pages may supply visual review for an identical build. A new layout needs a full review.

## Deliver and transfer

Deliver the generated PDF and briefly report its mode, page count and checks. Keep runtime details in the JSON report.

To install this exact package on another computer, run its `scripts/install_skill.py --setup`. It copies authored files and resources, recreates dependencies, and excludes inputs, outputs, caches, baselines and machine-specific virtual environments. The package in Git is the portable source of truth. Do not create a symlink to a repository as a substitute for the independent global copy.
