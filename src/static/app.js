// Confirmaciones: <form data-confirm="¿Seguro?">
document.addEventListener("submit", (e) => {
  const msg = e.target.dataset && e.target.dataset.confirm;
  if (msg && !confirm(msg)) e.preventDefault();
});

// Filas clicables: <tr data-href="/ruta">
document.querySelectorAll("tr[data-href]").forEach((tr) => {
  tr.addEventListener("click", (e) => {
    if (e.target.closest("a,button,form,input")) return;
    location.href = tr.dataset.href;
  });
});

// Buscador: <input data-filter="#tabla">
document.querySelectorAll("[data-filter]").forEach((input) => {
  const tabla = document.querySelector(input.dataset.filter);
  const contador = document.querySelector("[data-contador]");
  const filas = [...tabla.tBodies[0].rows].filter((r) => !r.querySelector(".vacio"));
  input.addEventListener("input", () => {
    const q = input.value.trim().toLowerCase();
    let visibles = 0;
    filas.forEach((tr) => {
      const oculta = q && !tr.textContent.toLowerCase().includes(q);
      tr.hidden = !!oculta;
      if (!oculta) visibles++;
    });
    if (contador) contador.textContent = visibles + " de " + filas.length;
  });
});

// Ordenación: <th data-sort="num|texto">, y en la celda data-v="valor"
document.querySelectorAll("th[data-sort]").forEach((th) => {
  th.addEventListener("click", () => {
    const tabla = th.closest("table");
    const idx = [...th.parentNode.children].indexOf(th);
    const dir = th.dataset.dir === "asc" ? "desc" : "asc";
    tabla.querySelectorAll("th[data-sort]").forEach((o) => delete o.dataset.dir);
    th.dataset.dir = dir;
    const valor = (tr) => {
      const c = tr.cells[idx];
      return c.dataset.v !== undefined ? c.dataset.v : c.textContent.trim();
    };
    const filas = [...tabla.tBodies[0].rows];
    filas.sort((a, b) => {
      if (th.dataset.sort === "num") return parseFloat(valor(a)) - parseFloat(valor(b));
      return valor(a).localeCompare(valor(b), "es", { sensitivity: "base" });
    });
    if (dir === "desc") filas.reverse();
    filas.forEach((f) => tabla.tBodies[0].appendChild(f));
  });
});

// Vista previa de colores en Ajustes
const preview = document.getElementById("preview");
if (preview) {
  const primario = document.querySelector("[name=color_primario]");
  const cabecera = document.querySelector("[name=color_cabecera]");
  const texto = (hex) => {
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255 > 0.6 ? "#0f172a" : "#ffffff";
  };
  const pintar = () => {
    preview.style.setProperty("--pv-h", cabecera.value);
    preview.style.setProperty("--pv-ht", texto(cabecera.value));
    preview.style.setProperty("--pv-p", primario.value);
    preview.style.setProperty("--pv-pt", texto(primario.value));
  };
  [primario, cabecera].forEach((i) => i.addEventListener("input", pintar));
  document.querySelectorAll("[data-restablecer]").forEach((b) =>
    b.addEventListener("click", () => {
      primario.value = b.dataset.primario;
      cabecera.value = b.dataset.cabecera;
      pintar();
    })
  );
  pintar();
}
