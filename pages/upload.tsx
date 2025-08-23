import { useEffect, useRef, useState } from "react";

type Report = { html: string; metadata: Record<string, any> };

async function apiUpload(file: File, docType: string) {
  const body = new FormData();
  body.append("file", file);
  body.append("doc_type", docType);
  const r = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/upload`, { method: "POST", body });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ document_id: string; status: string }>;
}

async function apiStatus(id: string) {
  const r = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/status/${id}`);
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ document_id: string; status: string; error_msg?: string }>;
}

async function apiReport(id: string) {
  const r = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/generate-report`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ document_id: id }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<Report>;
}

async function apiExportReport(id: string, fmt: "pdf" | "docx") {
  const r = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/export-report`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ document_id: id, fmt }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.blob();
}

export default function UploadPage() {
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [docId, setDocId] = useState<string | null>(null);
  const [status, setStatus] = useState<"idle" | "uploading" | "parsing" | "ready" | "error">("idle");
  const [err, setErr] = useState<string | null>(null);

  const [report, setReport] = useState<Report | null>(null);
  const [exportFmt, setExportFmt] = useState<"pdf" | "docx">("pdf");
  const [exporting, setExporting] = useState(false);

  const inputRef = useRef<HTMLInputElement>(null);

  const reset = () => {
    setFile(null);
    setDocId(null);
    setStatus("idle");
    setErr(null);
    setReport(null);
    if (inputRef.current) inputRef.current.value = "";
  };

  const onChoose = (f: File | undefined) => {
    if (!f) return;
    if (!/\.(pdf|txt|docx)$/i.test(f.name)) {
      setErr("Please select a .pdf, .txt, or .docx file.");
      return;
    }
    setErr(null);
    setFile(f);
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    onChoose(e.dataTransfer.files?.[0]);
  };

  const onUpload = async () => {
    if (!file) return;
    setErr(null);
    setStatus("uploading");
    try {
      const { document_id } = await apiUpload(file, "10-K"); // or "Other"
      setDocId(document_id);
      setStatus("parsing");
    } catch (e: any) {
      setStatus("error");
      setErr(e?.message ?? "Upload failed");
    }
  };

  useEffect(() => {
    if (!docId || status !== "parsing") return;
    const t = setInterval(async () => {
      try {
        const s = await apiStatus(docId);
        if (s.status === "ready") {
          setStatus("ready");
          clearInterval(t);
        } else if (s.status === "error") {
          setStatus("error");
          setErr(s.error_msg ?? "Parsing failed");
          clearInterval(t);
        }
      } catch (e: any) {
        setStatus("error");
        setErr(e?.message ?? "Status check failed");
        clearInterval(t);
      }
    }, 900);
    return () => clearInterval(t);
  }, [docId, status]);

  const onGenerateReport = async () => {
    if (!docId) return;
    setErr(null);
    try {
      const res = await apiReport(docId);
      setReport(res);
    } catch (e: any) {
      setErr(e?.message ?? "Report generation failed");
    }
  };

  const onExport = async () => {
    if (!docId) return;
    setExporting(true);
    setErr(null);
    try {
      const blob = await apiExportReport(docId, exportFmt);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${docId}_report.${exportFmt}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e: any) {
      setErr(e?.message ?? "Export failed");
    } finally {
      setExporting(false);
    }
  };

  const serverRestarted = docId && status !== "ready" && !report;

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="border-b bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between p-5">
          <h1 className="text-xl font-semibold tracking-tight">Doyrix — Analyze a Filing</h1>
          <div className="text-sm text-gray-500">MVP</div>
        </div>
      </header>

      <main className="mx-auto grid max-w-5xl gap-6 p-6 md:grid-cols-2">
        {/* LEFT: Upload card */}
        <section className="rounded-2xl border bg-white p-6 shadow-sm">
          <h2 className="mb-2 text-lg font-semibold">Upload a filing</h2>
          <p className="mb-4 text-sm text-gray-500">PDF, DOCX, or TXT. Drag & drop or click to browse.</p>

          <div
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            onClick={() => inputRef.current?.click()}
            className={`flex cursor-pointer items-center justify-center rounded-xl border-2 border-dashed p-8 text-center transition
              ${dragging ? "border-indigo-500 bg-indigo-50" : "border-gray-300 hover:border-gray-400"}`}
          >
            <div>
              <div className="mx-auto mb-2 h-10 w-10 rounded-full border bg-gray-50" />
              <div className="font-medium">{file ? file.name : "Drop file here or click to select"}</div>
              <div className="text-xs text-gray-500">{file ? `${(file.size / 1024 / 1024).toFixed(2)} MB` : "Max 50MB"}</div>
            </div>
            <input
              ref={inputRef}
              type="file"
              accept=".pdf,.docx,.txt"
              className="hidden"
              onChange={(e) => onChoose(e.target.files?.[0] as File | undefined)}
            />
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button
              onClick={onUpload}
              disabled={!file || status === "uploading" || status === "parsing"}
              className="rounded-xl bg-black px-4 py-2 text-white disabled:opacity-50"
            >
              {status === "uploading" ? "Uploading…" : status === "parsing" ? "Parsing…" : "Upload"}
            </button>
            <button onClick={reset} className="rounded-xl border px-3 py-2 text-gray-700 hover:bg-gray-50">
              Reset
            </button>

            {docId && (
              <span className="ml-auto truncate text-xs text-gray-500" title={docId}>
                ID: {docId}
              </span>
            )}

            <span
              className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium
                ${
                  status === "ready"
                    ? "bg-green-100 text-green-700"
                    : status === "parsing"
                    ? "bg-indigo-100 text-indigo-700"
                    : status === "error"
                    ? "bg-red-100 text-red-700"
                    : "bg-gray-100 text-gray-600"
                }`}
            >
              {status === "idle" && "Idle"}
              {status === "uploading" && "Uploading"}
              {status === "parsing" && "Parsing"}
              {status === "ready" && "Ready"}
              {status === "error" && "Error"}
            </span>
          </div>

          {err && <p className="mt-3 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">{err}</p>}

          {status === "ready" && (
            <div className="mt-5 flex flex-col gap-3">
              <button
                onClick={onGenerateReport}
                className="w-full rounded-xl border border-indigo-200 bg-indigo-50 px-4 py-2 text-indigo-700 hover:bg-indigo-100"
              >
                Generate Analyst Report (Multi-Page)
              </button>

              <div className="flex items-center gap-3">
                <label className="text-sm text-gray-600">
                  Format:&nbsp;
                  <select
                    className="rounded-md border px-2 py-1"
                    value={exportFmt}
                    onChange={(e) => setExportFmt(e.target.value as "pdf" | "docx")}
                  >
                    <option value="pdf">PDF</option>
                    <option value="docx">DOCX</option>
                  </select>
                </label>
                <button
                  onClick={onExport}
                  disabled={exporting || !report}
                  className="rounded-xl bg-black px-4 py-2 text-white disabled:opacity-50"
                >
                  {exporting ? "Exporting…" : "Export Report"}
                </button>
              </div>
            </div>
          )}

          {serverRestarted && (
            <p className="mt-3 text-xs text-amber-700">
              If export fails after a server restart, please re-upload to get a fresh ID.
            </p>
          )}
        </section>

        {/* RIGHT: Preview card */}
        <section className="rounded-2xl border bg-white p-6 shadow-sm">
          <h2 className="mb-2 text-lg font-semibold">Preview</h2>
          <p className="mb-4 text-sm text-gray-500">Your generated analyst report will render here.</p>
          <div className="relative h-[520px] overflow-auto rounded-xl border bg-gray-50 p-4 scroll-smooth">
            {!report ? (
              <div className="grid h-full place-items-center text-sm text-gray-400">No content yet</div>
            ) : (
              <div className="prose max-w-none" dangerouslySetInnerHTML={{ __html: report.html }} />
            )}
          </div>
          {report?.metadata && (
            <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-gray-500 md:grid-cols-3">
              {"citations_count" in report.metadata && <div>Citations: {report.metadata.citations_count ?? "—"}</div>}
              {"financial_tables" in report.metadata && <div>Tables: {report.metadata.financial_tables ?? "—"}</div>}
              {"kpi_count" in report.metadata && <div>KPIs: {report.metadata.kpi_count ?? "—"}</div>}
              {"risk_count" in report.metadata && <div>Risks: {report.metadata.risk_count ?? "—"}</div>}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
