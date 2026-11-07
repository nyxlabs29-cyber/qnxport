CC = gcc
CFLAGS = -O2 -march=native
OS := $(shell uname -s)
ifeq ($(OS),Linux)
LDLIBS += -lrt -ldl -lpthread
endif
app: main.o
	$(CC) -o $@ $^ $(LDLIBS)
