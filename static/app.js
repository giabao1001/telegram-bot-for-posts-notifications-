document.addEventListener("click", (event) => {
  const reveal = event.target.closest("[data-reveal]");
  if (reveal) {
    const input = document.getElementById(reveal.dataset.reveal);
    const showing = input.type === "text";
    input.type = showing ? "password" : "text";
    reveal.textContent = showing ? document.body.dataset.show : document.body.dataset.hide;
  }
});

document.querySelectorAll("form[data-confirm]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  });
});

document.querySelectorAll("form").forEach((form) => {
  form.addEventListener("submit", () => {
    const button = form.querySelector('button[type="submit"]');
    if (button && !button.disabled) {
      button.dataset.originalText = button.textContent;
      button.textContent = document.body.dataset.working;
      button.disabled = true;
    }
  });
});
