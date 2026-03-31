NVCC ?= nvcc
NVCCFLAGS ?= -O2
LDFLAGS ?= -lcublas

TARGET = gpu_stress

.PHONY: all clean

all: $(TARGET)

$(TARGET): gpu_stress.cu
	$(NVCC) $(NVCCFLAGS) -o $@ $< $(LDFLAGS)

clean:
	rm -f $(TARGET)
