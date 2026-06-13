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
