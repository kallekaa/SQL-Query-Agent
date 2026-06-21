document.addEventListener("DOMContentLoaded", () => {
  const form = document.querySelector("#question-form");
  const questionInput = document.querySelector("#question");
  const askButton = document.querySelector("#ask-button");
  const statusText = document.querySelector("#status");
  const results = document.querySelector("#results");

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const question = questionInput.value.trim();
    if (!question) {
      questionInput.focus();
      return;
    }

    setLoading(true);
    results.replaceChildren();

    try {
      const response = await fetch("/api/ask", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({question}),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "Request failed.");
      }
      renderResults(payload);
      statusText.textContent = "Done";
    } catch (error) {
      renderError(error.message || String(error));
      statusText.textContent = "Error";
    } finally {
      setLoading(false);
    }
  });

  function setLoading(isLoading) {
    askButton.disabled = isLoading;
    askButton.textContent = isLoading ? "Asking..." : "Ask";
    statusText.textContent = isLoading ? "Working..." : "";
  }

  function renderResults(payload) {
    results.appendChild(panel("Answer", renderMarkdown(payload.answer || "(no answer)")));

    if (Array.isArray(payload.sql_queries) && payload.sql_queries.length > 0) {
      const container = document.createElement("div");
      payload.sql_queries.forEach((sql) => {
        container.appendChild(codeBlock(sql));
      });
      results.appendChild(panel("SQL", container));
    }

    if (Array.isArray(payload.query_results) && payload.query_results.length > 0) {
      payload.query_results.forEach((result, index) => {
        results.appendChild(panel(
          payload.query_results.length > 1 ? `Result ${index + 1}` : "Result",
          renderQueryResult(result),
        ));
      });
    }
  }

  function renderMarkdown(markdown) {
    const root = document.createElement("div");
    root.className = "markdown";
    const text = String(markdown || "");

    if (!window.marked || !window.DOMPurify) {
      root.textContent = text;
      return root;
    }

    const parser = typeof window.marked.parse === "function" ? window.marked.parse : window.marked;
    const unsafeHtml = parser(text, {gfm: true, breaks: false});
    root.innerHTML = window.DOMPurify.sanitize(unsafeHtml);

    root.querySelectorAll("a[href]").forEach((anchor) => {
      if (!isSafeLink(anchor.href)) {
        anchor.removeAttribute("href");
        return;
      }
      anchor.target = "_blank";
      anchor.rel = "noreferrer";
    });

    root.querySelectorAll("table").forEach((table) => {
      if (table.parentElement && table.parentElement.classList.contains("table-wrap")) {
        return;
      }
      const wrapper = document.createElement("div");
      wrapper.className = "table-wrap";
      table.replaceWith(wrapper);
      wrapper.appendChild(table);
    });

    return root;
  }

  function renderQueryResult(result) {
    const wrapper = document.createElement("div");
    if (result.error) {
      wrapper.appendChild(textBlock(result.error, "error"));
      return wrapper;
    }

    const columns = Array.isArray(result.columns) ? result.columns : [];
    const rows = Array.isArray(result.rows) ? result.rows : [];
    if (columns.length === 0) {
      wrapper.appendChild(textBlock("(no columns)", ""));
      return wrapper;
    }

    wrapper.appendChild(resultTable(columns, rows));

    const meta = document.createElement("p");
    meta.className = "query-meta";
    const count = Number.isInteger(result.row_count) ? result.row_count : rows.length;
    meta.textContent = result.truncated
      ? `${count} rows shown; result truncated.`
      : `${count} rows.`;
    wrapper.appendChild(meta);
    return wrapper;
  }

  function resultTable(columns, rows) {
    const tableWrap = document.createElement("div");
    tableWrap.className = "table-wrap";
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const headerRow = document.createElement("tr");
    columns.forEach((column) => {
      const th = document.createElement("th");
      th.textContent = column;
      headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      columns.forEach((column) => {
        const td = document.createElement("td");
        const value = row && Object.prototype.hasOwnProperty.call(row, column) ? row[column] : "";
        td.textContent = value === null || value === undefined ? "" : String(value);
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    tableWrap.appendChild(table);
    return tableWrap;
  }

  function panel(title, child) {
    const section = document.createElement("section");
    section.className = "panel";
    const heading = document.createElement("h2");
    heading.className = "section-title";
    heading.textContent = title;
    section.appendChild(heading);
    section.appendChild(child);
    return section;
  }

  function codeBlock(text) {
    const pre = document.createElement("pre");
    const code = document.createElement("code");
    code.textContent = text;
    pre.appendChild(code);
    return pre;
  }

  function textBlock(text, className) {
    const div = document.createElement("div");
    if (className) {
      div.className = className;
    }
    div.textContent = text;
    return div;
  }

  function renderError(message) {
    results.appendChild(panel("Error", textBlock(message, "error")));
  }

  function isSafeLink(url) {
    try {
      const parsed = new URL(url, window.location.href);
      return ["http:", "https:", "mailto:"].includes(parsed.protocol);
    } catch {
      return false;
    }
  }
});
