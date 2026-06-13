// Доп-задания (extra.js / extra_c.js) подмешиваются в пул соответствующих уроков.
(function mergeExtra(course, extra) {
  if (!course || !extra) return;
  course.forEach(u => u.lessons.forEach(l => {
    if (Array.isArray(extra[l.id]) && extra[l.id].length) l.ex = l.ex.concat(extra[l.id]);
  }));
})(window.COURSE, window.EXTRA_CPP);
(function mergeExtraC(course, extra) {
  if (!course || !extra) return;
  course.forEach(u => u.lessons.forEach(l => {
    if (Array.isArray(extra[l.id]) && extra[l.id].length) l.ex = l.ex.concat(extra[l.id]);
  }));
})(window.COURSE_C, window.EXTRA_C);

// Расширенные конспекты (theory.js / theory_c.js) перекрывают исходный th урока.
(function mergeTheory(course, th) {
  if (!course || !th) return;
  course.forEach(u => u.lessons.forEach(l => {
    if (typeof th[l.id] === 'string' && th[l.id].trim()) l.th = th[l.id];
  }));
})(window.COURSE, window.THEORY_CPP);
(function mergeTheoryC(course, th) {
  if (!course || !th) return;
  course.forEach(u => u.lessons.forEach(l => {
    if (typeof th[l.id] === 'string' && th[l.id].trim()) l.th = th[l.id];
  }));
})(window.COURSE_C, window.THEORY_C);

// Сборка языков: C++ (из data.js) и C / Основы программирования (из data_c.js).
window.PLAYGROUND_CPP = `#include <iostream>

int main() {
    std::cout << "Hello, C++!" << std::endl;
    return 0;
}`;
window.PLAYGROUND_C = `#include <stdio.h>

int main(void) {
    printf("Hello, C!\\n");
    return 0;
}`;

window.LANGS = {
  cpp: {
    id: 'cpp', name: 'C++', badge: 'C++', accent: '#58cc02', runLang: 'cpp', std: 'C++17',
    blurb: 'ООП, шаблоны, STL — экзамен по C++',
    course: window.COURSE, tickets: window.TICKETS, challenges: window.CODE_CHALLENGES,
    playground: window.PLAYGROUND_CPP,
  },
  c: {
    id: 'c', name: 'C', badge: 'C', accent: '#1cb0f6', runLang: 'c', std: 'C11',
    blurb: 'Указатели, память, структуры данных — экзамен по основам программирования (ОП)',
    course: window.COURSE_C, tickets: window.TICKETS_C, challenges: window.CODE_CHALLENGES_C,
    playground: window.PLAYGROUND_C,
  },
};
