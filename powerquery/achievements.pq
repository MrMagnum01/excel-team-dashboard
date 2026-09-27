// Power Query (M) - achievements
// Requires a text Parameter named FolderPath (see tasks.pq / README.md).
let
    Source = Csv.Document(
        File.Contents(FolderPath & "achievements.csv"),
        [Delimiter=",", Columns=5, Encoding=65001, QuoteStyle=QuoteStyle.Csv]
    ),
    PromotedHeaders = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    ChangedType = Table.TransformColumnTypes(PromotedHeaders, {
        {"achievement_id", type text}, {"team", type text}, {"member", type text},
        {"week_ending", type date}, {"description", type text}
    })
in
    ChangedType
