// SPDX-License-Identifier: CC0-1.0

#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>

#include <ia_cmc_parser.h>

static void dump_general(const ia_cmc_t *cmc) {
    if (!cmc || !cmc->cmc_general_data) {
        return;
    }
    const cmc_general_data_t *g = cmc->cmc_general_data;
    printf("general_data:\n");
    printf("  width=%u height=%u bit_depth=%u packed_bit_depth=%u color_order=%u\n",
           g->width, g->height, g->bit_depth, g->bit_depth_packed, g->color_order);
}

static void dump_chromaticity(const ia_cmc_t *cmc) {
    if (!cmc || !cmc->cmc_parsed_chromaticity_response.cmc_chromaticity_response) {
        return;
    }
    const cmc_chromaticity_response_t *cr =
        cmc->cmc_parsed_chromaticity_response.cmc_chromaticity_response;
    const cmc_lightsource_t *avg = cmc->cmc_parsed_chromaticity_response.cmc_lightsources_avg;
    printf("chromaticity_response:\n");
    printf("  avg_light_sources=%u nvm_light_sources=%u\n",
           cr->num_lightsources, cr->num_nvm_lightsources);
    if (!avg) {
        return;
    }
    for (uint16_t i = 0; i < cr->num_lightsources; ++i) {
        printf("  [%u] rg=%u bg=%u cie=(%u,%u)\n",
               i,
               avg[i].chromaticity_response.r_per_g,
               avg[i].chromaticity_response.b_per_g,
               avg[i].cie_coords.x,
               avg[i].cie_coords.y);
    }
}

static void dump_color_matrices(const ia_cmc_t *cmc) {
    if (!cmc || !cmc->cmc_parsed_color_matrices.cmc_color_matrices ||
        !cmc->cmc_parsed_color_matrices.cmc_color_matrix) {
        return;
    }
    const cmc_color_matrices_t *cms = cmc->cmc_parsed_color_matrices.cmc_color_matrices;
    const cmc_color_matrix_t *m = cmc->cmc_parsed_color_matrices.cmc_color_matrix;
    printf("color_matrices:\n");
    printf("  num_matrices=%u\n", cms->num_matrices);
    for (uint16_t i = 0; i < cms->num_matrices; ++i) {
        printf("  [%u] source=%u rg=%u bg=%u cie=(%u,%u)\n",
               i,
               m[i].light_src_type,
               m[i].chromaticity.r_per_g,
               m[i].chromaticity.b_per_g,
               m[i].cie_coords.x,
               m[i].cie_coords.y);
        printf("    accurate_raw=[%" PRId32 ", %" PRId32 ", %" PRId32 ", %" PRId32 ", %" PRId32 ", %" PRId32 ", %" PRId32 ", %" PRId32 ", %" PRId32 "]\n",
               m[i].matrix_accurate[0], m[i].matrix_accurate[1], m[i].matrix_accurate[2],
               m[i].matrix_accurate[3], m[i].matrix_accurate[4], m[i].matrix_accurate[5],
               m[i].matrix_accurate[6], m[i].matrix_accurate[7], m[i].matrix_accurate[8]);
        printf("    preferred_raw=[%" PRId32 ", %" PRId32 ", %" PRId32 ", %" PRId32 ", %" PRId32 ", %" PRId32 ", %" PRId32 ", %" PRId32 ", %" PRId32 "]\n",
               m[i].matrix_preferred[0], m[i].matrix_preferred[1], m[i].matrix_preferred[2],
               m[i].matrix_preferred[3], m[i].matrix_preferred[4], m[i].matrix_preferred[5],
               m[i].matrix_preferred[6], m[i].matrix_preferred[7], m[i].matrix_preferred[8]);
    }
}

static void dump_black_level(const ia_cmc_t *cmc) {
    printf("black_level:\n");
    if (cmc && cmc->cmc_black_level_global && cmc->cmc_black_level_global->bl_values.ptr) {
        const cmc_black_level_global *bl = cmc->cmc_black_level_global;
        printf("  global_num_luts=%u\n", bl->num_bl_luts);
        for (uint32_t i = 0; i < bl->num_bl_luts; ++i) {
            const cmc_black_level_values *v = &bl->bl_values.ptr[i];
            printf("  [global %u] exposure=%u total_gain=%.6f first_row=[%.6f %.6f %.6f %.6f]\n",
                   i, v->exposure_time, v->total_gain,
                   v->black_level[0][0], v->black_level[0][1],
                   v->black_level[0][2], v->black_level[0][3]);
        }
        return;
    }
    if (cmc && cmc->cmc_parsed_black_level.cmc_black_level &&
        cmc->cmc_parsed_black_level.cmc_black_level_luts) {
        const cmc_black_level_t *bl = cmc->cmc_parsed_black_level.cmc_black_level;
        const cmc_black_level_lut_t *lut = cmc->cmc_parsed_black_level.cmc_black_level_luts;
        printf("  parsed_num_luts=%u\n", bl->num_bl_luts);
        for (uint32_t i = 0; i < bl->num_bl_luts; ++i) {
            printf("  [parsed %u] exposure=%u analog_gain=%u channels=[%u %u %u %u]\n",
                   i, lut[i].exposure_time, lut[i].analog_gain,
                   lut[i].color_channels.cc1, lut[i].color_channels.cc2,
                   lut[i].color_channels.cc3, lut[i].color_channels.cc4);
        }
        return;
    }
    printf("  unavailable\n");
}

static void dump_lsc(const ia_cmc_t *cmc) {
    if (!cmc) {
        return;
    }
    if (cmc->cmc_lens_shading) {
        const cmc_lens_shading_correction *lsc = cmc->cmc_lens_shading;
        printf("lsc_4x4:\n");
        printf("  num_light_srcs=%u grid=%ux%u\n",
               lsc->num_light_srcs, lsc->grid_width, lsc->grid_height);
        for (uint16_t i = 0; i < lsc->num_light_srcs; ++i) {
            const cmc_lsc_grid *g = &lsc->lsc_grids[i];
            printf("  [%u] source=%u rg=%.6f bg=%.6f cie=(%.6f,%.6f) frac_bits=%u\n",
                   i, g->source_type,
                   g->chromaticity.r_per_g, g->chromaticity.b_per_g,
                   g->cie_coords.x, g->cie_coords.y,
                   g->fraction_bits);
        }
        return;
    }
    if (cmc->cmc_parsed_lens_shading.cmc_lens_shading) {
        const cmc_lens_shading_t *lsc = cmc->cmc_parsed_lens_shading.cmc_lens_shading;
        printf("lsc_legacy:\n");
        printf("  num_grids=%u grid=%ux%u level=%u\n",
               lsc->num_grids, lsc->grid_width, lsc->grid_height, lsc->lsc_level);
    }
}

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "usage: %s <file.aiqb>\n", argv[0]);
        return 2;
    }

    const char *path = argv[1];
    FILE *f = fopen(path, "rb");
    if (!f) {
        perror(path);
        return 1;
    }
    if (fseek(f, 0, SEEK_END) != 0) {
        perror("fseek");
        fclose(f);
        return 1;
    }
    long sz = ftell(f);
    if (sz < 0) {
        perror("ftell");
        fclose(f);
        return 1;
    }
    rewind(f);

    void *buf = malloc((size_t)sz);
    if (!buf) {
        fprintf(stderr, "malloc failed\n");
        fclose(f);
        return 1;
    }
    if (fread(buf, 1, (size_t)sz, f) != (size_t)sz) {
        fprintf(stderr, "short read\n");
        free(buf);
        fclose(f);
        return 1;
    }
    fclose(f);

    ia_binary_data aiqb = {
        .data = buf,
        .size = (unsigned int)sz,
    };

    fprintf(stderr, "loading %s (%ld bytes)\n", path, sz);
    fflush(stderr);
    ia_cmc_t *cmc = ia_cmc_parser_init_v1(&aiqb, NULL);
    if (!cmc) {
        fprintf(stderr, "ia_cmc_parser_init_v1 failed\n");
        free(buf);
        return 1;
    }
    fprintf(stderr, "parser ok\n");
    fflush(stderr);

    printf("file: %s\n", path);
    fprintf(stderr, "dump general\n");
    fflush(stderr);
    dump_general(cmc);
    fprintf(stderr, "dump chromaticity\n");
    fflush(stderr);
    dump_chromaticity(cmc);
    fprintf(stderr, "dump color matrices\n");
    fflush(stderr);
    dump_color_matrices(cmc);
    fprintf(stderr, "dump black level\n");
    fflush(stderr);
    dump_black_level(cmc);
    fprintf(stderr, "dump lsc\n");
    fflush(stderr);
    dump_lsc(cmc);

    fprintf(stderr, "deinit\n");
    fflush(stderr);
    ia_cmc_parser_deinit(cmc);
    free(buf);
    return 0;
}
