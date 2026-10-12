# Sources (accessed 2026-10-12)

| # | Name | Link | Used for |
|---|------|------|----------|
| 1 | OpenStreetMap contributors, Open Database License (ODbL) | https://www.openstreetmap.org/copyright | Building outlines, names, floor counts (`data/buildings.geojson`) |
| 1a | ODbL 1.0 text | https://opendatacommons.org/licenses/odbl/1-0/ | License of the OpenStreetMap data |
| 1b | Overpass API | https://overpass-api.de/ | Downloading the OpenStreetMap data |
| 1c | Nominatim geocoder | https://nominatim.openstreetmap.org/ | Locating Albion College's bounding box |
| 1d | CARTO basemaps and attribution | https://carto.com/basemaps/ , https://carto.com/attributions | Map background tiles shown in the app |
| 2 | Albion College Office of the Registrar, Course Schedules | https://www.albion.edu/offices/registrar/course-schedules/ | Page describing the public schedule |
| 2a | Albion College public course search (Fall 2026 = term 202630) | https://adminpagesprod02.albion.edu:7443/StudentRegistrationSsb/ssb/term/termSelection?mode=search | Class days, start/end times, buildings, rooms (`data/202630_meetings.csv`) |
| 3 | Albion College, "Albion College Joins Climate Leadership Network, Commits to Action", by Chuck Carlson, posted 2020-12-18 | https://www.albion.edu/post/albion-college-joins-climate-leadership-network-commits-to-action/ | Campus electricity: "about 14 million kilowatt hours" (no period stated) |
| 4 | NOAA NCEI, U.S. Climate Normals 1991-2020 (monthly) | https://www.ncei.noaa.gov/products/land-based-station/us-climate-normals | Monthly heating degree days |
| 4a | NOAA data file, Jackson Reynolds Field, MI (USW00014833) | https://www.ncei.noaa.gov/data/normals-monthly/1991-2020/access/USW00014833.csv | `data/hdd_jackson_1991_2020.csv` (annual total 6,469.6) |
| 5 | U.S. EIA, Commercial Buildings Energy Consumption Survey 2018, Table E6 (release December 2022) | https://www.eia.gov/consumption/commercial/data/2018/ce/pdf/e6.pdf | National comparison only: education buildings 9.4 kWh/ft2/yr (read directly from the table) |
| 5a | Albion Registrar FAQ | https://www.albion.edu/offices/registrar/frequently-asked-questions/ | 1 Albion unit = 4 semester hours (credit hours) |
| 5b | U.S. EIA, 2024 Average Monthly Bill - Commercial (Table 5.B) | https://www.eia.gov/electricity/sales_revenue_price/pdf/table_5B.pdf | Michigan commercial electricity price, 14.01 cents/kWh (cost pages) |
| 5c | Albion Registrar Academic Calendar | https://www.albion.edu/offices/registrar/academic-calendar/ | Fall 2026 class days |
| 6 | U.S. EIA, Units and calculators | https://www.eia.gov/energyexplained/units-and-calculators/ | 1 MMBtu = 293.07 kWh |
| 7 | Streamlit, pydeck/deck.gl, pandas, Altair | see THIRD_PARTY_NOTICES.md | Software |

## Things deliberately NOT used
- Floor plans or CAD drawings of any building (none are public for the academic buildings).
- Albion's AASHE STARS report: its pages now require a login, so its figures could not be verified and were removed.
- Course titles, descriptions, instructor names, or any information about individual students. The fetch script keeps only course code, building, room, day, start/end time, credit units and the aggregate seat count (enrollment) of each section.
- Any code from other people's Power BI visuals or reverse-engineering tools.

## Limits to keep in mind
- Albion publishes only one campus-wide electricity number we could verify, and no public heating total. All building and room energy values are **modeled allocations**, not measurements.
- The electricity article gives no period (assumed one year), is rounded, and is from December 2020.
- Which heating system each building uses is not public, so none is claimed.
- Floor counts come from OpenStreetMap where present, otherwise from room numbers in the schedule.
- Class counts are classes in session, not people. The walking figures are a simulated illustration.
- Three schedule building names were matched to map names by judgment (Kresge Science Bldg to Kresge Hall, Herrick Speech and Theater to Herrick Center, Astronomical Observatory to Observatory); check `BUILDING_ALIASES` in `campus_data.py`.

## Licensing notes
- `data/buildings.geojson` is derived from OpenStreetMap data. Under the ODbL, if you publish it or a database built from it, keep the attribution "(c) OpenStreetMap contributors" and offer the derived data under the ODbL.
- Schedule facts (times, places) are factual data read from Albion's public service at a low request rate. This project is unofficial and not affiliated with or endorsed by Albion College. If you publish it, check Albion's website terms of use or ask the Registrar's office.
- This is not legal advice.
