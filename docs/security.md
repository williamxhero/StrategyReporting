# HTML security

Templates use Jinja autoescape and strict undefined values. Dynamic values are never marked safe.
Generated documents are validated before publication: no remote resources, forms, object/embed/base,
event-handler attributes, JavaScript URLs, `eval`, `new Function`, or dynamic `innerHTML`. CSP limits
resources to the document itself. Plotly is embedded by Nautilus.

Model, HTML, small source JSON and detail-row sizes are independently bounded. Large normalized
output is materialized through the public Workspace API and parsed as a stream; it is never fetched
through the base64 read API. All artifact content identities are verified before use. Portal
filenames are fixed content identities and resolved destinations must remain inside the requested
output root. Source/report listings fail closed at the 10,000-record cap.
