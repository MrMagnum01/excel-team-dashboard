// Power Query (M) - blockers
// Requires a text Parameter named FolderPath (see tasks.pq / README.md).
let
    Source = Csv.Document(
        File.Contents(FolderPath & "blockers.csv"),
        [Delimiter=",", Columns=8, Encoding=65001, QuoteStyle=QuoteStyle.Csv]
    ),
    PromotedHeaders = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    ChangedType = Table.TransformColumnTypes(PromotedHeaders, {
        {"blocker_id", type text}, {"team", type text}, {"task_id", type text},
        {"owner", type text}, {"description", type text},
        {"raised_date", type date}, {"status", type text},
        {"resolved_date", type date}
    }),
    AddAgeDays = Table.AddColumn(ChangedType, "age_days", each
        if [status] = "Open" then Duration.Days(DateTime.LocalNow() - DateTime.From([raised_date])) else null,
        Int64.Type
    )
in
    AddAgeDays
