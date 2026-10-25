# Self-hosted dashboard fonts

The dashboard loads these fonts from the same origin, not a runtime Google Fonts
stylesheet. Google serves user-agent-dependent CSS, which cannot have one stable
SRI digest. Vendoring the actual font bytes removes that external stylesheet
trust dependency and permits `style-src` / `font-src` self-only on the SPA.

These are **unmodified variable WOFF2 files**, with descriptive local filenames.
Font-family names and Unicode ranges are unchanged. All 16 subsets returned by
Google Fonts are retained, including Cyrillic, Greek, Vietnamese and Latin
extensions where the family provides them. Normal weights 400–700 retain the
previous dashboard weights (400, 500, 600, 700; JetBrains previously 400/500/700).
`font-display: swap` and the existing fallback stacks are unchanged.

## Provenance

Retrieved 2026-10-24 from the official Google Fonts CSS API:

```
https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400..700&family=JetBrains+Mono:wght@400..700&family=Inter:wght@400..700&display=swap
```

User-Agent used to select WOFF2 variable fonts:

```
Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36
```

Each file below pins the downloaded bytes by SHA-256. No network fetch happens
at build time or runtime. For updates, retrieve from these official sources,
review licenses/Unicode ranges, replace assets and update all checksums together.
Do not add a runtime CDN fallback.

## Font assets

| Local file | SHA-256 | Official source |
| --- | --- | --- |
| `inter-cyrillic-ext.woff2` | `ca157063339ac4ad418f214f3abfed119b0798ab4d377386ce5c9e5a7a435ebd` | [https://fonts.gstatic.com/s/inter/v20/UcC73FwrK3iLTeHuS_nVMrMxCp50SjIa2JL7SUc.woff2](https://fonts.gstatic.com/s/inter/v20/UcC73FwrK3iLTeHuS_nVMrMxCp50SjIa2JL7SUc.woff2) |
| `inter-cyrillic.woff2` | `71d5ee93cc1e9f1d520a3a8b66456de18c7879d8df09d57fcd2eaff75fef0075` | [https://fonts.gstatic.com/s/inter/v20/UcC73FwrK3iLTeHuS_nVMrMxCp50SjIa0ZL7SUc.woff2](https://fonts.gstatic.com/s/inter/v20/UcC73FwrK3iLTeHuS_nVMrMxCp50SjIa0ZL7SUc.woff2) |
| `inter-greek-ext.woff2` | `6e9e020a25f9b56d418f2c085b1d3c09725a4da23fe693a5b463064606732190` | [https://fonts.gstatic.com/s/inter/v20/UcC73FwrK3iLTeHuS_nVMrMxCp50SjIa2ZL7SUc.woff2](https://fonts.gstatic.com/s/inter/v20/UcC73FwrK3iLTeHuS_nVMrMxCp50SjIa2ZL7SUc.woff2) |
| `inter-greek.woff2` | `1be3448e292fbf05ffe176fe1e43f135013d50b1e7d324ad1a558f623d3bb6f6` | [https://fonts.gstatic.com/s/inter/v20/UcC73FwrK3iLTeHuS_nVMrMxCp50SjIa1pL7SUc.woff2](https://fonts.gstatic.com/s/inter/v20/UcC73FwrK3iLTeHuS_nVMrMxCp50SjIa1pL7SUc.woff2) |
| `inter-vietnamese.woff2` | `5c66f9e07e90c6d4ac4922cc68d60de26c17b1858e677fb5e603fce3952b3ff2` | [https://fonts.gstatic.com/s/inter/v20/UcC73FwrK3iLTeHuS_nVMrMxCp50SjIa2pL7SUc.woff2](https://fonts.gstatic.com/s/inter/v20/UcC73FwrK3iLTeHuS_nVMrMxCp50SjIa2pL7SUc.woff2) |
| `inter-latin-ext.woff2` | `34b9c504cab7a73e37b746343a449132e56cf7b5481af2cb81dc74dcff25c956` | [https://fonts.gstatic.com/s/inter/v20/UcC73FwrK3iLTeHuS_nVMrMxCp50SjIa25L7SUc.woff2](https://fonts.gstatic.com/s/inter/v20/UcC73FwrK3iLTeHuS_nVMrMxCp50SjIa25L7SUc.woff2) |
| `inter-latin.woff2` | `3100e775e8616cd2611beecfa23a4263d7037586789b43f035236a2e6fbd4c62` | [https://fonts.gstatic.com/s/inter/v20/UcC73FwrK3iLTeHuS_nVMrMxCp50SjIa1ZL7.woff2](https://fonts.gstatic.com/s/inter/v20/UcC73FwrK3iLTeHuS_nVMrMxCp50SjIa1ZL7.woff2) |
| `jetbrains-mono-cyrillic-ext.woff2` | `62213be8a78b42f1e29d1452d91e2f8b3e745572a9dd98d3941e39fa00b37d76` | [https://fonts.gstatic.com/s/jetbrainsmono/v24/tDbv2o-flEEny0FZhsfKu5WU4zr3E_BX0PnT8RD8yKwBNntkaToggR7BYRbKPx3cwhsk.woff2](https://fonts.gstatic.com/s/jetbrainsmono/v24/tDbv2o-flEEny0FZhsfKu5WU4zr3E_BX0PnT8RD8yKwBNntkaToggR7BYRbKPx3cwhsk.woff2) |
| `jetbrains-mono-cyrillic.woff2` | `e17cfd15fb96909d64095015f958207063a0c07191da3512df7d560a781aebdf` | [https://fonts.gstatic.com/s/jetbrainsmono/v24/tDbv2o-flEEny0FZhsfKu5WU4zr3E_BX0PnT8RD8yKwBNntkaToggR7BYRbKPxTcwhsk.woff2](https://fonts.gstatic.com/s/jetbrainsmono/v24/tDbv2o-flEEny0FZhsfKu5WU4zr3E_BX0PnT8RD8yKwBNntkaToggR7BYRbKPxTcwhsk.woff2) |
| `jetbrains-mono-greek.woff2` | `0a557721b1f8b36d3f3f84442689a71ca4a744300abcb46a1953f51bfc663b66` | [https://fonts.gstatic.com/s/jetbrainsmono/v24/tDbv2o-flEEny0FZhsfKu5WU4zr3E_BX0PnT8RD8yKwBNntkaToggR7BYRbKPxPcwhsk.woff2](https://fonts.gstatic.com/s/jetbrainsmono/v24/tDbv2o-flEEny0FZhsfKu5WU4zr3E_BX0PnT8RD8yKwBNntkaToggR7BYRbKPxPcwhsk.woff2) |
| `jetbrains-mono-vietnamese.woff2` | `c89b9cc0bc6262bd4f8d8494b6961601f3aefa829d08c2e3635f4d501d3a47c2` | [https://fonts.gstatic.com/s/jetbrainsmono/v24/tDbv2o-flEEny0FZhsfKu5WU4zr3E_BX0PnT8RD8yKwBNntkaToggR7BYRbKPx_cwhsk.woff2](https://fonts.gstatic.com/s/jetbrainsmono/v24/tDbv2o-flEEny0FZhsfKu5WU4zr3E_BX0PnT8RD8yKwBNntkaToggR7BYRbKPx_cwhsk.woff2) |
| `jetbrains-mono-latin-ext.woff2` | `db5ff4db83e580426280e9337a58dc57d3a83784a1b03ad80914651594441d52` | [https://fonts.gstatic.com/s/jetbrainsmono/v24/tDbv2o-flEEny0FZhsfKu5WU4zr3E_BX0PnT8RD8yKwBNntkaToggR7BYRbKPx7cwhsk.woff2](https://fonts.gstatic.com/s/jetbrainsmono/v24/tDbv2o-flEEny0FZhsfKu5WU4zr3E_BX0PnT8RD8yKwBNntkaToggR7BYRbKPx7cwhsk.woff2) |
| `jetbrains-mono-latin.woff2` | `83c005d49d8a6a50474c73a5a36ac0468076e9c4a29da7bdb14995d80560a5be` | [https://fonts.gstatic.com/s/jetbrainsmono/v24/tDbv2o-flEEny0FZhsfKu5WU4zr3E_BX0PnT8RD8yKwBNntkaToggR7BYRbKPxDcwg.woff2](https://fonts.gstatic.com/s/jetbrainsmono/v24/tDbv2o-flEEny0FZhsfKu5WU4zr3E_BX0PnT8RD8yKwBNntkaToggR7BYRbKPxDcwg.woff2) |
| `space-grotesk-vietnamese.woff2` | `8895e3d49825128bfa5238e4c96e9b432d7a3dadbe5c17c6081267398305dc71` | [https://fonts.gstatic.com/s/spacegrotesk/v22/V8mDoQDjQSkFtoMM3T6r8E7mPb54C-s0.woff2](https://fonts.gstatic.com/s/spacegrotesk/v22/V8mDoQDjQSkFtoMM3T6r8E7mPb54C-s0.woff2) |
| `space-grotesk-latin-ext.woff2` | `952dddb45d2f96f71cbf3b7f510b24379afc3c89ea02fcf89d377b45d62c0166` | [https://fonts.gstatic.com/s/spacegrotesk/v22/V8mDoQDjQSkFtoMM3T6r8E7mPb94C-s0.woff2](https://fonts.gstatic.com/s/spacegrotesk/v22/V8mDoQDjQSkFtoMM3T6r8E7mPb94C-s0.woff2) |
| `space-grotesk-latin.woff2` | `0640890476fc1198ab4de571fb658de443c4d85b66466ec09534a8737ab1ce9d` | [https://fonts.gstatic.com/s/spacegrotesk/v22/V8mDoQDjQSkFtoMM3T6r8E7mPbF4Cw.woff2](https://fonts.gstatic.com/s/spacegrotesk/v22/V8mDoQDjQSkFtoMM3T6r8E7mPbF4Cw.woff2) |

Total vendored font bytes: 332744.

## Licenses

Each family is distributed under SIL Open Font License 1.1. The complete
upstream copyright and license wording are preserved (whitespace normalized).
License source is pinned to `google/fonts` commit `e7db6ca603fd4862010383ff17ffd6cc4ffac1c0`.

| Local license | SHA-256 | Pinned official source |
| --- | --- | --- |
| `inter-OFL.txt` | `5dd548d31a85f756e01d63e00d7faf1e324103ed3e9102fcbbabf2cc2db6dd39` | [inter-OFL.txt](https://raw.githubusercontent.com/google/fonts/e7db6ca603fd4862010383ff17ffd6cc4ffac1c0/ofl/inter/OFL.txt) |
| `jetbrainsmono-OFL.txt` | `b2fe5e8987594e9ffd1d2ca52a2f5d73eb8335243893c5d6254b5ad69269591d` | [jetbrainsmono-OFL.txt](https://raw.githubusercontent.com/google/fonts/e7db6ca603fd4862010383ff17ffd6cc4ffac1c0/ofl/jetbrainsmono/OFL.txt) |
| `spacegrotesk-OFL.txt` | `18a4de52385f6b988782639d5d0cc1326e5a8c2de9a7f01d7b20d9aedcc60943` | [spacegrotesk-OFL.txt](https://raw.githubusercontent.com/google/fonts/e7db6ca603fd4862010383ff17ffd6cc4ffac1c0/ofl/spacegrotesk/OFL.txt) |

License wording is preserved; vendored license files use normalized LF line endings and no trailing whitespace.
