# Third-party licences

Every library this project installs, and the licence it ships under, as
read from each package's installed distribution metadata
(`importlib.metadata`, `License-Expression` / `License` field or trove
classifier). All are open source; no closed-source or paid dependency is
used anywhere in this project.

## Direct dependencies (pinned in `requirements.txt`)

| Library | Pinned version | Licence | Used for |
|---|---|---|---|
| [openpyxl](https://pypi.org/project/openpyxl/) | 3.1.5 | MIT | Building/reading `.xlsx` workbooks: input workbook, data validation, dashboards, native charts |
| [pytest](https://pypi.org/project/pytest/) | 9.1.1 | MIT | Test suite |

## Transitive dependencies (not pinned; versions from a clean install)

| Library | Resolved version | Licence | Pulled in by |
|---|---|---|---|
| [et_xmlfile](https://pypi.org/project/et-xmlfile/) | 2.0.0 | MIT | openpyxl (low-level XML writer) |
| [iniconfig](https://pypi.org/project/iniconfig/) | 2.3.0 | MIT | pytest |
| [packaging](https://pypi.org/project/packaging/) | 26.3 | Apache-2.0 OR BSD-2-Clause | pytest |
| [pluggy](https://pypi.org/project/pluggy/) | 1.6.0 | MIT | pytest |
| [Pygments](https://pypi.org/project/Pygments/) | 2.21.0 | BSD-2-Clause | pytest |

No pandas, no charting library, no HTTP client: the dependency set is
deliberately this short. CSV I/O is the Python standard library
(`csv`, `pathlib`, `json`, `datetime`); the trend chart is a native
`openpyxl.chart.LineChart` object, not an image or an external plotting
library.

## Notices

These licences require their copyright and licence notices to be kept with
any copy or redistribution. This repository does not vendor or redistribute
any of these packages; they are installed from PyPI. Each installed package
carries its own licence and notice files, and those must be preserved in
any distribution that includes them.

No paid or closed-source service is used anywhere in this project.
