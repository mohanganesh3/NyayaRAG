from __future__ import annotations

from app.ingestion.scripts.law_commission_reports import (
    discover_law_commission_pages,
    extract_commission_page_details,
    parse_law_commission_page,
)


def test_discover_law_commission_pages_extracts_commission_links() -> None:
    html = """
    <html><body>
      <div>First Law Commission ( 1 to 14 ) (Chairman Mr. M. C. Setalvad 1955-1958)
      <a href="/report_first/">Click Here</a></div>
      <div>Twenty-Second Law Commission ( 278 to 289) (Chairman, Justice Ritu Raj Awasthi 2020-2024)
      <a href="/report_twentysecond/">Click Here</a></div>
    </body></html>
    """

    pages = discover_law_commission_pages(html, "https://lawcommissionofindia.nic.in/")

    assert [page.url for page in pages] == [
        "https://lawcommissionofindia.nic.in/report_first/",
        "https://lawcommissionofindia.nic.in/report_twentysecond/",
    ]


def test_extract_commission_page_details_resolves_title_and_chairman() -> None:
    html = """
    <html><head><title>Twenty-Second Law Commission Report
    | Law Commission of India | India</title></head>
    <body>
      <h1>Twenty-Second Law Commission Report</h1>
      <div>(Chairman, Justice Ritu Raj Awasthi 2020-2024) Report No.
      Subject Year of submission Download pdf</div>
    </body></html>
    """

    page = extract_commission_page_details(
        html,
        "https://lawcommissionofindia.nic.in/report_twentysecond/",
    )

    assert page.title == "Twenty-Second Law Commission Report"
    assert "Ritu Raj Awasthi" in (page.chairman or "")


def test_parse_law_commission_page_extracts_rows_and_parts() -> None:
    html = """
    <html><body>
      <h1>Twenty-Second Law Commission Report</h1>
      <div>(Chairman, Justice Ritu Raj Awasthi 2020-2024) Report No.
      Subject Year of submission Download pdf</div>
      <div>278 Urgent Need to Amend Rule 14(4) of Order VII of the
      Code of Civil Procedure, 1908 17th March 2023
        <a href="https://cdn.example/278.pdf">Click Here</a>
      </div>
      <div>280 The Law on Adverse Possession 17th May 2023
      <a href="https://cdn.example/280.pdf">Click Here</a></div>
      <div>– Dissent Note 17th May 2023
      <a href="https://cdn.example/280-dissent.pdf">Click Here</a></div>
      <div>289 Trade Secrets and Economic Espionage 17th March 2024
        <a href="https://cdn.example/289-part1.pdf">Part 1</a>
        <a href="https://cdn.example/289-part2.pdf">Part 2</a>
      </div>
    </body></html>
    """

    rows = parse_law_commission_page(
        html,
        "https://lawcommissionofindia.nic.in/report_twentysecond/",
        "Twenty-Second Law Commission Report",
    )

    assert [row.report_number for row in rows] == ["278", "280", "280", "289", "289"]
    assert rows[0].submission_date == "17th March 2023"
    assert rows[1].note_kind is None
    assert rows[2].note_kind == "dissent_note"
    assert {row.part_label for row in rows if row.report_number == "289"} == {"Part 1", "Part 2"}
    assert rows[0].pdf_url == "https://cdn.example/278.pdf"
