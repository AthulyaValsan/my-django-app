# from django.shortcuts import render

# def book_list(request):
#     books = ['The Hobbit', 'Pride and Prejudice', 'Dune']
#     context = {'books': books}
#     return render(request, 'booklist/book_list.html', context)

from django.shortcuts import render, get_object_or_404
from .models import Book
from .forms import BookForm
from django.http import HttpResponseRedirect, HttpResponse
from django.urls import reverse

def book_list(request):
    raise ValueError("Intentional error for Sentry PR.")
    books = Book.objects.all()
    return render(request, 'booklist/book_list.html', {'books': books})

def book_detail(request, book_id):
    book = get_object_or_404(Book, pk=book_id)
    return render(request, 'booklist/book_detail.html', {'book': book})

def add_book(request):
    if request.method == 'POST':
        form = BookForm(request.POST)
        if form.is_valid():
            form.save()
            return HttpResponseRedirect(reverse('book_list'))
    else:
        form = BookForm()
    return render(request, 'booklist/add_book.html', {'form': form})
