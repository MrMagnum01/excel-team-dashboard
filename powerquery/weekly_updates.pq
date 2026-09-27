// Power Query (M) - weekly_updates
// Requires a text Parameter named FolderPath (see tasks.pq / README.md).
let
    Source = Csv.Document(
        File.Contents(FolderPath & "weekly_updates.csv"),
        [Delimiter=",", Columns=6, Encoding=65001, QuoteStyle=QuoteStyle.Csv]
    ),
    PromotedHeaders = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    ChangedType = Table.TransformColumnTypes(PromotedHeaders, {
        {"update_id", type text}, {"team", type text}, {"member", type text},
        {"week_ending", type date}, {"summary", type text},
        {"hours_logged", type number}
    })
in
    ChangedType
