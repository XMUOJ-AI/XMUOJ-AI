export function getCSRFHeaders () {
  const cookie = document.cookie.split(';').map(value => value.trim()).find(value => value.startsWith('csrftoken='))
  return cookie ? {'X-CSRFToken': decodeURIComponent(cookie.slice('csrftoken='.length))} : {}
}
