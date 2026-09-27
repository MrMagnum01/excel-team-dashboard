// Power Query (M) - tasks
// Requires a text Parameter named FolderPath pointing at the folder that
// holds tasks.csv, weekly_updates.csv, blockers.csv, achievements.csv and
// kpi_targets.csv (the CSVs written by `team_dashboard generate` / `sync`).
// See README.md in this folder for how to paste this in.
let
    Source = Csv.Document(
        File.Contents(FolderPath & "tasks.csv"),
        [Delimiter=",", Columns=8, Encoding=65001, QuoteStyle=QuoteStyle.Csv]
    ),
    PromotedHeaders = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    ChangedType = Table.TransformColumnTypes(PromotedHeaders, {
        {"task_id", type text}, {"team", type text}, {"owner", type text},
        {"title", type text}, {"status", type text},
        {"planned_date", type date}, {"done_date", type date},
        {"created_date", type date}
    })
in
    ChangedType
