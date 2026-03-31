/*
 * gpu_stress - Synthetic GPU workload for testing IOPS GPU probes.
 *
 * Performs repeated dense matrix multiplications (SGEMM via cuBLAS)
 * to generate a predictable, sustained GPU load. Designed to exercise
 * power draw, utilization, memory, and thermals for probe validation.
 *
 * Usage:
 *   gpu_stress [--duration SECONDS] [--size MATRIX_SIZE] [--gpu GPU_INDEX]
 *
 * Defaults:
 *   --duration 10      Run for 10 seconds
 *   --size 4096        4096x4096 matrices (about 192 MiB, ~high utilization)
 *   --gpu 0            Use GPU 0
 *
 * Build:
 *   make              (uses Makefile)
 *   nvcc -O2 -o gpu_stress gpu_stress.cu -lcublas
 *
 * The program prints a JSON summary to stdout on completion:
 *   {"duration_s": 10.02, "matrix_size": 4096, "gflops": 1234.5, "iterations": 42}
 */

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <cuda_runtime.h>
#include <cublas_v2.h>

#define CHECK_CUDA(call)                                                       \
    do {                                                                        \
        cudaError_t err = (call);                                              \
        if (err != cudaSuccess) {                                              \
            fprintf(stderr, "CUDA error at %s:%d: %s\n", __FILE__, __LINE__,  \
                    cudaGetErrorString(err));                                   \
            exit(1);                                                           \
        }                                                                      \
    } while (0)

#define CHECK_CUBLAS(call)                                                     \
    do {                                                                        \
        cublasStatus_t status = (call);                                        \
        if (status != CUBLAS_STATUS_SUCCESS) {                                 \
            fprintf(stderr, "cuBLAS error at %s:%d: %d\n", __FILE__, __LINE__,\
                    (int)status);                                              \
            exit(1);                                                           \
        }                                                                      \
    } while (0)

static double get_time() {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec * 1e-9;
}

static void print_usage(const char *prog) {
    fprintf(stderr, "Usage: %s [--duration SECONDS] [--size MATRIX_SIZE] [--gpu GPU_INDEX]\n", prog);
    fprintf(stderr, "\nOptions:\n");
    fprintf(stderr, "  --duration SECONDS    Run duration in seconds (default: 10)\n");
    fprintf(stderr, "  --size MATRIX_SIZE    Square matrix dimension (default: 4096)\n");
    fprintf(stderr, "  --gpu GPU_INDEX       GPU device index (default: 0)\n");
}

int main(int argc, char *argv[]) {
    int duration = 10;
    int matrix_size = 4096;
    int gpu_index = 0;

    /* Parse arguments */
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--duration") == 0 && i + 1 < argc) {
            duration = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--size") == 0 && i + 1 < argc) {
            matrix_size = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--gpu") == 0 && i + 1 < argc) {
            gpu_index = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--help") == 0 || strcmp(argv[i], "-h") == 0) {
            print_usage(argv[0]);
            return 0;
        } else {
            fprintf(stderr, "Unknown argument: %s\n", argv[i]);
            print_usage(argv[0]);
            return 1;
        }
    }

    /* Select GPU */
    int device_count = 0;
    CHECK_CUDA(cudaGetDeviceCount(&device_count));
    if (gpu_index >= device_count) {
        fprintf(stderr, "GPU index %d not available (found %d GPUs)\n", gpu_index, device_count);
        return 1;
    }
    CHECK_CUDA(cudaSetDevice(gpu_index));

    cudaDeviceProp prop;
    CHECK_CUDA(cudaGetDeviceProperties(&prop, gpu_index));
    fprintf(stderr, "GPU %d: %s (%.0f MiB)\n", gpu_index, prop.name,
            prop.totalGlobalMem / (1024.0 * 1024.0));
    fprintf(stderr, "Matrix size: %dx%d, Duration: %d seconds\n", matrix_size, matrix_size, duration);

    /* Allocate matrices on device */
    size_t n = (size_t)matrix_size;
    size_t bytes = n * n * sizeof(float);

    float *d_A, *d_B, *d_C;
    CHECK_CUDA(cudaMalloc(&d_A, bytes));
    CHECK_CUDA(cudaMalloc(&d_B, bytes));
    CHECK_CUDA(cudaMalloc(&d_C, bytes));

    /* Initialize with random data on host, copy to device */
    float *h_buf = (float *)malloc(bytes);
    if (!h_buf) {
        fprintf(stderr, "Host allocation failed\n");
        return 1;
    }

    srand(42);
    for (size_t i = 0; i < n * n; i++) {
        h_buf[i] = (float)rand() / RAND_MAX;
    }
    CHECK_CUDA(cudaMemcpy(d_A, h_buf, bytes, cudaMemcpyHostToDevice));

    for (size_t i = 0; i < n * n; i++) {
        h_buf[i] = (float)rand() / RAND_MAX;
    }
    CHECK_CUDA(cudaMemcpy(d_B, h_buf, bytes, cudaMemcpyHostToDevice));
    free(h_buf);

    /* Create cuBLAS handle */
    cublasHandle_t handle;
    CHECK_CUBLAS(cublasCreate(&handle));

    float alpha = 1.0f, beta = 0.0f;

    /* Warm up */
    CHECK_CUBLAS(cublasSgemm(handle, CUBLAS_OP_N, CUBLAS_OP_N,
                             n, n, n, &alpha, d_A, n, d_B, n, &beta, d_C, n));
    CHECK_CUDA(cudaDeviceSynchronize());

    /* Run SGEMM in a loop for the specified duration */
    long iterations = 0;
    double t_start = get_time();
    double t_end = t_start + (double)duration;

    while (get_time() < t_end) {
        CHECK_CUBLAS(cublasSgemm(handle, CUBLAS_OP_N, CUBLAS_OP_N,
                                 n, n, n, &alpha, d_A, n, d_B, n, &beta, d_C, n));
        iterations++;

        /* Sync every 10 iterations to check time without excessive overhead */
        if (iterations % 10 == 0) {
            CHECK_CUDA(cudaDeviceSynchronize());
        }
    }
    CHECK_CUDA(cudaDeviceSynchronize());
    double elapsed = get_time() - t_start;

    /* Compute GFLOPS: SGEMM does 2*N^3 FLOPs */
    double total_flops = 2.0 * (double)n * (double)n * (double)n * (double)iterations;
    double gflops = total_flops / elapsed / 1e9;

    fprintf(stderr, "Completed %ld iterations in %.2f seconds (%.1f GFLOPS)\n",
            iterations, elapsed, gflops);

    /* Output JSON result to stdout (for IOPS parser) */
    printf("{\"duration_s\": %.2f, \"matrix_size\": %d, \"gflops\": %.1f, \"iterations\": %ld}\n",
           elapsed, matrix_size, gflops, iterations);

    /* Cleanup */
    cublasDestroy(handle);
    cudaFree(d_A);
    cudaFree(d_B);
    cudaFree(d_C);

    return 0;
}
