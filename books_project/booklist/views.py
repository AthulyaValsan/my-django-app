from django.shortcuts import render

def book_list(request):
    books = ['The Hobbit', 'Pride and Prejudice', 'Dune']
    context = {'books': books}
    return render(request, 'booklist/book_list.html', context)