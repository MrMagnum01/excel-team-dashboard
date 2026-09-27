// Power Query (M) - kpi_targets
// Requires a text Parameter named FolderPath (see tasks.pq / README.md).
let
    Source = Csv.Document(
        File.Contents(FolderPath & "kpi_targets.csv"),
        [Delimiter=",", Columns=4, Encoding=65001, QuoteStyle=QuoteStyle.Csv]
    ),
    PromotedHeaders = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    ChangedType = Table.TransformColumnTypes(PromotedHeaders, {
        {"team", type text}, {"week_ending", type date},
        {"planned_tasks", Int64.Type}, {"target_done", Int64.Type}
    })
in
    ChangedType
