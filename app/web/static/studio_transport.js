/* HTTP errors, interrupted requests and UI errors must not look alike. */
(() => {
  'use strict';
  async function decode(response) {
    let body;
    try { body = await response.json(); }
    catch (cause) {
      // A received HTTP 500/401/413 is not a lost connection.
      if (response.ok) {
        const error = new Error('Сервер вернул неполный ответ. Обновите черновик перед повтором.');
        error.kind = 'response'; error.reload = true; throw error;
      }
    }
    if (!response.ok) {
      const detail = body?.detail;
      const message = Array.isArray(detail) ? detail.map(row => row.msg).join('; ') : typeof detail === 'string' ? detail : '';
      const fallback = response.status === 401 ? 'Нужно заново войти на сайт.'
        : response.status === 413 ? 'Файл слишком большой для загрузки. Уменьшите PDF и повторите.'
        : response.status === 409 ? 'Версия или открытый проект изменились. Обновите черновик после сохранения копии своего ввода; автоматического повтора нет.'
        : response.status >= 500 ? 'Ошибка на сервере. Обновите черновик перед повтором: действие могло сохраниться.'
        : 'Не удалось выполнить запрос.';
      const error = new Error(message || fallback);
      error.status = response.status;
      if(response.status===422 && Array.isArray(body?.input_issues)) {
        error.inputIssues=body.input_issues;
        error.inputMessage=typeof body.input_message==='string'?body.input_message:null;
      }
      error.reload = response.status === 409 || response.status >= 500;
      throw error;
    }
    return body;
  }
  function interrupted(cause) {
    const error = new Error(cause?.name === 'AbortError'
      ? 'Сервер не успел ответить. Обновите черновик перед повтором: действие могло сохраниться.'
      : 'Связь с сервером прервалась. Действие могло сохраниться: обновите черновик перед повтором.');
    error.kind = 'network'; error.reload = true;
    return error;
  }
  function presentation(error) {
    if (error.status || error.kind) return {message: error.message, reload: Boolean(error.reload)};
    return {message: 'Не удалось отобразить результат. Обновите черновик; повторно загружать документы пока не нужно.', reload: true};
  }
  window.ZaryaTransport = {decode, interrupted, presentation};
})();
